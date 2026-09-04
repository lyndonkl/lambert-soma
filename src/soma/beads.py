"""Cell-side Beads (ladder PR-08): a per-cell board and five scoped tools.

Cell Protocol T1/T3/T4: a cell sees only scoped board operations on its
own claims — bd_ready, bd_claim, bd_close, bd_create (discovered-from),
bd_note — and never queries above its scope. The board is per cell:
`bd init` runs in ~/.soma/boards/<key>/ (keyed by the cell's bundle,
outside any project — bd refuses to nest a board inside another bd
workspace), so the cell's whole board world is a board nobody else
writes to. The project's board is unreachable by construction, not
by policy.

bd 1.2.2 facts this code relies on (probed 2026-09-02, see EXP-004):
- `--json` shapes: create/comment return an object carrying
  schema_version; update/close/ready return arrays of issues; errors
  return {"error": ..., "schema_version": 1} with exit code 1.
- There is no `bd events` CLI and `events-journal` is not a recognized
  config key. The journal IS event beads (`--type=event`), listed with
  `bd list --type event`. claim/close emit one each.
- Embedded Dolt is single-writer per board; per-cell boards sidestep
  contention entirely (EXP-004 measures the alternative).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openhands.sdk.tool import (
    Action,
    Observation,
    ToolAnnotations,
    ToolDefinition,
    ToolExecutor,
    register_tool,
)
from pydantic import Field

BD_SUPPORTED_SERIES = "1.2"
RUN_PREFIX = "cell"
BEADS_TOOL_NAMES = ("bd_ready", "bd_claim", "bd_close", "bd_create", "bd_note")
_BD_TIMEOUT = 60


# --- runner ---------------------------------------------------------------

@dataclass
class BdResult:
    ok: bool
    data: Any = None
    error: str | None = None


class BdRunner:
    """One board, one subprocess boundary. Every call goes through run()."""

    def __init__(self, board_dir: Path, prefix: str = RUN_PREFIX):
        self.board_dir = Path(board_dir)
        self.prefix = prefix

    @property
    def id_prefix(self) -> str:
        return f"{self.prefix}-"

    def bootstrap(self) -> None:
        """`bd init` once per board. Verifies the board actually landed here."""
        if (self.board_dir / ".beads").is_dir():
            return
        self.board_dir.mkdir(parents=True, exist_ok=True)
        if shutil.which("bd") is None:
            raise RuntimeError("bd is not installed — cells need it for board ops (soma doctor)")
        proc = subprocess.run(
            ["bd", "init", "--prefix", self.prefix, "--quiet"],
            cwd=self.board_dir, capture_output=True, text=True, timeout=_BD_TIMEOUT,
            check=False,
        )
        # Trust the artifact, not the exit code: bd init also tries to `git init`
        # the directory and can exit non-zero on git template trouble while the
        # board itself is complete and usable (seen live, EXP-004).
        if not (self.board_dir / ".beads").is_dir():
            raise RuntimeError(
                f"bd init failed in {self.board_dir}: {proc.stderr.strip()[:200]}"
            )

    def run(self, *args: str) -> BdResult:
        """`bd <args> --json` -> parsed data, or an actionable error. Never raises."""
        try:
            proc = subprocess.run(
                ["bd", *args, "--json"], cwd=self.board_dir,
                capture_output=True, text=True, timeout=_BD_TIMEOUT, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return BdResult(False, error=f"bd could not run ({exc}) — check: soma doctor")
        text = proc.stdout.strip()
        if not text:
            return BdResult(False, error=(
                f"bd returned nothing (exit {proc.returncode}): {proc.stderr.strip()[:200]}"))
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return BdResult(False, error=(
                f"bd returned non-JSON for `bd {' '.join(args)}` (exit {proc.returncode}): "
                f"{text[:160]!r} — is bd {BD_SUPPORTED_SERIES}.x installed? run: soma doctor"))
        if isinstance(data, dict) and "error" in data:
            return BdResult(False, error=str(data["error"]))
        return BdResult(True, data=data)

    def ready(self) -> BdResult:
        return self.run("ready", "--exclude-type=epic")

    def claim(self, bead_id: str) -> BdResult:
        return self.run("update", bead_id, "--claim")

    def close(self, bead_id: str, reason: str) -> BdResult:
        return self.run("close", bead_id, "--reason", reason or "done")

    def create(self, title: str, description: str, priority: int,
               discovered_from: str | None) -> BdResult:
        args = ["create", "--title", title, "--type", "task",
                "--priority", str(priority), "--description", description or title]
        if discovered_from:
            args += ["--deps", f"discovered-from:{discovered_from}"]
        return self.run(*args)

    def note(self, bead_id: str, text: str) -> BdResult:
        return self.run("comment", bead_id, text)

    def emit_event(self, title: str, payload: dict) -> BdResult:
        """The 1.2.2 journal: an event bead per lifecycle moment."""
        return self.run("create", "--title", title, "--type", "event",
                        "--event-payload", json.dumps(payload))


def bd_version() -> str | None:
    if shutil.which("bd") is None:
        return None
    try:
        out = subprocess.run(["bd", "--version"], capture_output=True, text=True,
                             timeout=10, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    parts = out.split()
    if len(parts) >= 3 and parts[1] == "version":
        return parts[2]
    return out.strip() or None


def check_bd() -> list[tuple[bool | None, str]]:
    """Doctor lines: is bd here, and is it the series this code was probed against."""
    version = bd_version()
    if version is None:
        return [(False, ("bd (beads) not installed — cells cannot claim work; "
                         "see https://github.com/gastownhall/beads"))]
    ok = version.startswith(BD_SUPPORTED_SERIES + ".")
    if ok:
        return [(True, f"bd {version}")]
    return [(None, (f"bd {version} — soma is probed against {BD_SUPPORTED_SERIES}.x; "
                    "--json shapes may differ"))]


# --- the cell's scope -----------------------------------------------------

@dataclass
class CellBoard:
    """Runner + this cell's claims. Shared by the five tools of one cell."""

    runner: BdRunner
    claimed: list[str] = field(default_factory=list)

    def _open_on_board(self) -> list[str]:
        """The board is the truth, not this object's memory.

        The SDK can hand different tool-executor copies to different calls,
        so an in-memory claim list may be empty while the bead IS claimed on
        this cell's board. The board is per cell by construction, so every
        in_progress bead on it is this cell's own claim (T3 holds by
        construction). Seen live in PR-09: bd_claim ok, bd_close refused.
        """
        listed = self.runner.run("list", "--status=in_progress")
        return [b["id"] for b in (listed.data or []) if b.get("id")] if listed.ok else []

    @property
    def current(self) -> str | None:
        if self.claimed:
            return self.claimed[-1]
        open_ids = self._open_on_board()
        if open_ids:
            self.claimed.extend(open_ids)
            return self.claimed[-1]
        return None

    def in_scope(self, bead_id: str) -> str | None:
        if not bead_id.startswith(self.runner.id_prefix):
            return (f"'{bead_id}' is not on this cell's board (ids here start with "
                    f"'{self.runner.id_prefix}') — a cell never reaches above its scope (T3)")
        return None

    def mine(self, bead_id: str) -> str | None:
        if bead_id in self.claimed or bead_id in self._open_on_board():
            if bead_id not in self.claimed:
                self.claimed.append(bead_id)
            return None
        return (f"'{bead_id}' is not a bead this cell claimed — a cell may only "
                f"close/note its own claims (T3); claimed so far: {self.claimed or 'none'}")


_BOARDS: dict[str, CellBoard] = {}
# Boards live OUTSIDE any project: `bd init` refuses to nest inside an existing
# bd workspace (walks up and finds the project's own .beads), and run bundles
# sit inside the repo. Each board carries origin.txt pointing at its bundle.
BOARDS_ROOT = Path(os.environ.get("SOMA_BOARDS_ROOT", "~/.soma/boards")).expanduser()


def board_dir_for(persistence_dir: str | Path | None) -> Path:
    if persistence_dir:
        key = hashlib.sha256(str(Path(persistence_dir).resolve()).encode()).hexdigest()[:12]
    else:
        key = f"ephemeral-{uuid.uuid4().hex[:8]}"
    return BOARDS_ROOT / key


def board_for(persistence_dir: str | Path | None) -> CellBoard:
    """One CellBoard per conversation, keyed by its bundle dir; lazy bootstrap."""
    key = str(Path(persistence_dir).resolve()) if persistence_dir else f"<{uuid.uuid4()}>"
    if key not in _BOARDS:
        runner = BdRunner(board_dir_for(persistence_dir))
        runner.bootstrap()
        (runner.board_dir / "origin.txt").write_text(f"{persistence_dir or '(ephemeral)'}\n")
        _BOARDS[key] = CellBoard(runner)
    return _BOARDS[key]


# --- actions / observation ------------------------------------------------

class BdReadyAction(Action):
    """List the beads on this cell's board that are ready to work."""


class BdClaimAction(Action):
    bead_id: str = Field(description="Id of a ready bead on this board to claim.")


class BdCloseAction(Action):
    bead_id: str = Field(description="Id of a bead this cell claimed.")
    reason: str = Field(default="", description="One line on what was done.")


class BdCreateAction(Action):
    title: str = Field(description="Short title for work you discovered but will not do now.")
    description: str = Field(default="", description="Why it matters; what needs doing.")
    priority: int = Field(default=2, description="0 (critical) .. 4 (backlog).")


class BdNoteAction(Action):
    bead_id: str = Field(description="Id of a bead this cell claimed.")
    text: str = Field(description="Progress note to attach.")


class BdObservation(Observation):
    data: Any = Field(default=None, description="Parsed bd JSON, when any.")


def _obs(result: BdResult, ok_text: str) -> BdObservation:
    if not result.ok:
        return BdObservation.from_text(text=result.error or "bd failed", is_error=True)
    return BdObservation.from_text(text=ok_text, data=result.data)


def _refuse(reason: str) -> BdObservation:
    return BdObservation.from_text(text=reason, is_error=True)


# --- executors ------------------------------------------------------------

class _BoardExec(ToolExecutor):
    def __init__(self, board: CellBoard):
        self.board = board


class _ReadyExec(_BoardExec):
    def __call__(self, action, conversation=None):
        r = self.board.runner.ready()
        if not r.ok:
            return _obs(r, "")
        lines = [f"{b['id']}  P{b.get('priority', '?')}  {b.get('title', '')}" for b in r.data]
        return _obs(r, "\n".join(lines) or "no ready beads — idle (T1)")


class _ClaimExec(_BoardExec):
    def __call__(self, action, conversation=None):
        why = self.board.in_scope(action.bead_id)
        if why:
            return _refuse(why)
        r = self.board.runner.claim(action.bead_id)
        if r.ok:
            self.board.claimed.append(action.bead_id)
            self.board.runner.emit_event(f"claimed {action.bead_id}",
                                         {"bead": action.bead_id, "kind": "claim"})
        return _obs(r, f"claimed {action.bead_id} — it is your task now (T1)")


class _CloseExec(_BoardExec):
    def __call__(self, action, conversation=None):
        why = self.board.in_scope(action.bead_id) or self.board.mine(action.bead_id)
        if why:
            return _refuse(why)
        r = self.board.runner.close(action.bead_id, action.reason)
        if r.ok:
            self.board.runner.emit_event(f"closed {action.bead_id}",
                                         {"bead": action.bead_id, "kind": "close",
                                          "reason": action.reason})
        return _obs(r, f"closed {action.bead_id}")


class _CreateExec(_BoardExec):
    def __call__(self, action, conversation=None):
        parent = self.board.current
        if parent is None:
            return _refuse("no claimed bead — discoveries hang off your current task; "
                           "claim one first (T1/T4)")
        r = self.board.runner.create(action.title, action.description,
                                     action.priority, discovered_from=parent)
        new_id = r.data.get("id") if r.ok and isinstance(r.data, dict) else "?"
        return _obs(r, f"created {new_id} (discovered-from {parent}) — not yours to do now")


class _NoteExec(_BoardExec):
    def __call__(self, action, conversation=None):
        why = self.board.in_scope(action.bead_id) or self.board.mine(action.bead_id)
        if why:
            return _refuse(why)
        return _obs(self.board.runner.note(action.bead_id, action.text),
                    f"noted on {action.bead_id}")


# --- tool definitions (names derive from class names: BdReadyTool -> bd_ready) --

def _mk(cls, conv_state, description, action_type, executor_cls, read_only=False):
    board = board_for(getattr(conv_state, "persistence_dir", None))
    return [cls(
        description=description,
        action_type=action_type,
        observation_type=BdObservation,
        annotations=ToolAnnotations(readOnlyHint=read_only, destructiveHint=False,
                                    idempotentHint=read_only, openWorldHint=False),
        executor=executor_cls(board),
    )]


class BdReadyTool(ToolDefinition[BdReadyAction, BdObservation]):
    @classmethod
    def create(cls, conv_state=None, **_: Any) -> Sequence[BdReadyTool]:
        return _mk(cls, conv_state, "List ready beads on your board. No claimed bead "
                   "means you are idle.", BdReadyAction, _ReadyExec, read_only=True)


class BdClaimTool(ToolDefinition[BdClaimAction, BdObservation]):
    @classmethod
    def create(cls, conv_state=None, **_: Any) -> Sequence[BdClaimTool]:
        return _mk(cls, conv_state, "Claim a ready bead: it becomes your task.",
                   BdClaimAction, _ClaimExec)


class BdCloseTool(ToolDefinition[BdCloseAction, BdObservation]):
    @classmethod
    def create(cls, conv_state=None, **_: Any) -> Sequence[BdCloseTool]:
        return _mk(cls, conv_state, "Close a bead you claimed, once its work is done "
                   "and verified.", BdCloseAction, _CloseExec)


class BdCreateTool(ToolDefinition[BdCreateAction, BdObservation]):
    @classmethod
    def create(cls, conv_state=None, **_: Any) -> Sequence[BdCreateTool]:
        return _mk(cls, conv_state, "Record work you discovered but will not do now, "
                   "linked to your current bead.", BdCreateAction, _CreateExec)


class BdNoteTool(ToolDefinition[BdNoteAction, BdObservation]):
    @classmethod
    def create(cls, conv_state=None, **_: Any) -> Sequence[BdNoteTool]:
        return _mk(cls, conv_state, "Attach a progress note to a bead you claimed.",
                   BdNoteAction, _NoteExec)


for _tool_cls in (BdReadyTool, BdClaimTool, BdCloseTool, BdCreateTool, BdNoteTool):
    register_tool(_tool_cls.name, _tool_cls)
