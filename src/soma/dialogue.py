"""Cell-side dialogue participation (ladder PR-11) — Cell Protocol D1–D4.

This is the CELL half only. Brokering — creating the `dialogue:<id>`
channel, parking beads, alternating turns, the LOCAL summary and
teardown — is the team's job (ladder PR-18). Here a cell:

- receives an `invitation` event on its own channel naming a
  `dialogue:<id>` channel, and accepts by publishing `accept` there (D1)
- answers each peer `turn` with a harness-composed reply (D3):
  archetype core + dialogue-mode overlay + transcript + a one-line
  broader-goal reminder, through a direct `llm.completion` — no
  Conversation, no tools, no side effects; dialogues are talk
- emits `resolved` with a payload validated against a small schema
  when it judges the matter settled, or at the turn cap (D4)
- is PARKED while the dialogue is open (D2): `parked` is True and
  `assert_not_parked()` refuses a task step. The scheduler that never
  steps a parked cell is rung 2; the flag it will consult lives here.

The harness drives a participant with `tick()`: one call checks the
inbox for an invitation and answers any new peer turns.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ValidationError

from soma.wal import WalStore, cell_channel

KIND_INVITATION = "invitation"
KIND_ACCEPT = "accept"
KIND_TURN = "turn"
KIND_RESOLVED = "resolved"
DEFAULT_TURN_CAP = 12
_RESOLVED_RE = re.compile(r"RESOLVED\s*:\s*(\{.*\})", re.DOTALL)


class Resolution(BaseModel):
    """The small response_schema a RESOLVED move must satisfy (D4)."""

    outcome: Literal["agreed", "disagreed", "deferred"]
    summary: str
    next_steps: list[str] = []


class CellParked(RuntimeError):
    """Raised when something tries to step a cell's task engine mid-dialogue."""


def parse_resolution(text: str) -> Resolution | None:
    """Find `RESOLVED: {json}` in a reply and validate it; None if absent/invalid."""
    match = _RESOLVED_RE.search(text)
    if not match:
        return None
    try:
        return Resolution.model_validate_json(match.group(1))
    except ValidationError:
        return None


def _text_of(response) -> str:
    parts = getattr(response.message, "content", None) or []
    return "\n".join(
        getattr(p, "text", "") for p in parts if getattr(p, "text", "")
    ).strip()


@dataclass
class DialogueParticipant:
    """One cell's side of at most one dialogue at a time."""

    store: WalStore
    cell_id: str
    archetype_core: str
    llm: object  # an SDK LLM (or any object with .completion(messages))
    briefing: str
    overlay: str
    turn_cap: int = DEFAULT_TURN_CAP
    status: str = "idle"  # idle | in_dialogue | resolved
    channel: str | None = None
    peer: str | None = None
    transcript: list[tuple[str, str]] = field(default_factory=list)
    resolution: Resolution | None = None

    # --- parked state (D2) --------------------------------------------------
    @property
    def parked(self) -> bool:
        return self.status == "in_dialogue"

    def assert_not_parked(self) -> None:
        if self.parked:
            raise CellParked(
                f"{self.cell_id} is in {self.channel}; its task engine may not step"
            )

    # --- D1: invitation -> accept -------------------------------------------
    def check_invitations(self) -> str | None:
        """Read the cell's own channel; accept the first invitation seen."""
        if self.status != "idle":
            return None
        for event in self.store.read_new(self.cell_id, cell_channel(self.cell_id)):
            if event["kind"] != KIND_INVITATION:
                continue
            payload = json.loads(event["payload"])
            self.channel = payload["dialogue"]
            self.peer = payload.get("from") or event["author"]
            self.status = "in_dialogue"
            self.store.publish(
                self.channel, self.cell_id, KIND_ACCEPT, {"text": f"{self.cell_id} joined"}
            )
            return self.channel
        return None

    # --- D3/D4: answer turns, resolve ---------------------------------------
    def respond(self) -> str | None:
        """Consume new peer events; reply once if there is something to answer."""
        if self.status != "in_dialogue" or self.channel is None:
            return None
        new_peer_turn = False
        for event in self.store.read_new(self.cell_id, self.channel):
            if event["author"] == self.cell_id:
                continue
            if event["kind"] == KIND_RESOLVED:
                self.resolution = parse_resolution("RESOLVED: " + event["payload"])
                self.status = "resolved"
                return KIND_RESOLVED
            if event["kind"] == KIND_TURN:
                self.transcript.append(
                    (event["author"], json.loads(event["payload"])["text"])
                )
                new_peer_turn = True
        if not new_peer_turn:
            return None
        my_turns = sum(1 for author, _ in self.transcript if author == self.cell_id)
        if my_turns >= self.turn_cap:
            return self._resolve(Resolution(
                outcome="deferred", summary="turn cap reached without resolution",
                next_steps=["escalate to the team"],
            ))
        reply = self._compose()
        resolution = parse_resolution(reply)
        if resolution is None and "RESOLVED" in reply:
            resolution = self._retry_resolution(reply)  # validate-and-retry once
        if resolution is not None:
            return self._resolve(resolution)
        self.transcript.append((self.cell_id, reply))
        self.store.publish(self.channel, self.cell_id, KIND_TURN, {"text": reply})
        return KIND_TURN

    def tick(self) -> str | None:
        """One harness step: accept an invitation if any, then answer new turns."""
        return self.check_invitations() or self.respond()

    # --- composition (D3) ---------------------------------------------------
    def messages(self) -> list:
        from openhands.sdk import Message, TextContent

        lines = [f"{'you' if a == self.cell_id else a}: {t}" for a, t in self.transcript]
        schema = json.dumps(Resolution.model_json_schema()["properties"])
        user = (
            f"Broader goal — your task briefing: {self.briefing}\n\n"
            f"Dialogue with {self.peer} so far:\n" + "\n".join(lines) + "\n\n"
            "Your turn. If the matter is settled, end with a line "
            f"'RESOLVED: ' followed by JSON with fields {schema}."
        )
        system = f"{self.archetype_core}\n\n{self.overlay}"
        return [
            Message(role="system", content=[TextContent(text=system)]),
            Message(role="user", content=[TextContent(text=user)]),
        ]

    def _compose(self) -> str:
        return _text_of(self.llm.completion(self.messages()))

    def _retry_resolution(self, reply: str) -> Resolution | None:
        from openhands.sdk import Message, TextContent

        schema = json.dumps(Resolution.model_json_schema()["properties"])
        ask = Message(role="user", content=[TextContent(text=(
            f"Restate this resolution as one line 'RESOLVED: ' plus JSON "
            f"matching {schema}:\n{reply}"
        ))])
        return parse_resolution(_text_of(self.llm.completion([*self.messages(), ask])))

    def _resolve(self, resolution: Resolution) -> str:
        self.resolution = resolution
        self.status = "resolved"
        self.store.publish(
            self.channel, self.cell_id, KIND_RESOLVED, resolution.model_dump()
        )
        return KIND_RESOLVED
