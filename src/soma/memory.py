"""Memory points + death (ladder PR-12) — Cell Protocol X1–X4.

The cell level owns two small things about memory; the store itself
lands at Rung 4 (ADR-008, spike S12):

- `remember` — a cell may mark a salient moment during life (X3). The
  marker is recorded twice on purpose: as a `remember` event on the
  cell's own WAL channel (part of the activity log that reflection
  reads, X2), and in the MemoryStore (the drawer a real store will
  fill). Markers weight reflection; they never write memory directly.
- death is harness-side (X1): when a run reaches a terminal status the
  harness writes a `death` event on the cell's channel carrying the
  status, the marker count, and `reflection: requested` — the trigger
  a Rung-4 rider consumes. The bundle survives (X4).

MemoryStore is an interface with a stub: JSONL markers in the run
bundle. Rung 4 swaps in Mem0 or a custom store behind the same calls.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from openhands.sdk.tool import (
    Action,
    Observation,
    ToolAnnotations,
    ToolDefinition,
    ToolExecutor,
)
from pydantic import Field

MARKERS_FILENAME = "memory-markers.jsonl"
KIND_REMEMBER = "remember"
KIND_DEATH = "death"


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class MemoryStore(Protocol):
    """What the cell level needs from any memory store. Rung 4 adds
    episodes and recall behind the same object."""

    def mark(self, cell_id: str, archetype: str, text: str, tags: list[str]) -> str: ...

    def markers(self, cell_id: str) -> list[dict]: ...


class StubMemoryStore:
    """Markers as JSONL in the run bundle — the interface Rung 4 replaces."""

    def __init__(self, bundle_dir: Path | str):
        self.path = Path(bundle_dir) / MARKERS_FILENAME

    def mark(self, cell_id: str, archetype: str, text: str, tags: list[str]) -> str:
        marker = {
            "id": uuid.uuid4().hex[:8], "cell_id": cell_id, "archetype": archetype,
            "text": text, "tags": list(tags), "ts": _now_iso(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(marker) + "\n")
        return marker["id"]

    def markers(self, cell_id: str) -> list[dict]:
        if not self.path.is_file():
            return []
        rows = [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
        return [r for r in rows if r.get("cell_id") == cell_id]


# --- the remember tool ----------------------------------------------------

class RememberAction(Action):
    text: str = Field(description="The moment worth remembering, in one or two sentences.")
    tags: list[str] = Field(default_factory=list,
                            description="Optional labels: lesson, gotcha, decision, ...")


class RememberObservation(Observation):
    pass


class RememberExecutor(ToolExecutor):
    def __init__(self, bundle_dir: str, wal_path: str, cell_id: str, archetype: str):
        self.store = StubMemoryStore(bundle_dir)
        self.wal_path = wal_path
        self.cell_id = cell_id
        self.archetype = archetype

    def __call__(self, action, conversation=None):
        from soma.wal import WalStore, cell_channel

        marker_id = self.store.mark(self.cell_id, self.archetype, action.text, action.tags)
        wal = WalStore(self.wal_path)
        wal.publish(cell_channel(self.cell_id), self.cell_id, KIND_REMEMBER,
                    {"text": action.text, "tags": list(action.tags), "marker": marker_id})
        wal.close()
        return RememberObservation.from_text(
            f"remembered {marker_id} — it weights reflection at death; memory itself "
            "is written by the harness, not now"
        )


class RememberTool(ToolDefinition):
    @classmethod
    def create(cls, conv_state=None, **params: Any):
        executor = RememberExecutor(
            params["bundle_dir"], params["wal_path"], params["cell_id"], params["archetype"]
        )
        return [cls(
            description=("Mark a moment worth remembering — a lesson, a gotcha, a decision "
                         "and why. Cheap; use it when something would help a future cell "
                         "of your kind."),
            action_type=RememberAction, observation_type=RememberObservation,
            executor=executor,
            annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                        idempotentHint=False, openWorldHint=False),
        )]


_registered = False


def register_memory_tools() -> None:
    global _registered
    if _registered:
        return
    from openhands.sdk import register_tool

    register_tool("remember", RememberTool)
    _registered = True


def remember_tool_specs(bundle_dir: Path | str, wal_path: Path | str,
                        cell_id: str, archetype: str) -> list:
    from openhands.sdk import Tool

    register_memory_tools()
    return [Tool(name="remember", params={
        "bundle_dir": str(bundle_dir), "wal_path": str(wal_path),
        "cell_id": cell_id, "archetype": archetype,
    })]


# --- death ------------------------------------------------------------------

def write_death(wal, cell_id: str, status: str, archetype: str,
                bundle_dir: Path | str) -> str:
    """X1/X2: the harness records the death and requests reflection."""
    from soma.wal import cell_channel

    markers = len(StubMemoryStore(bundle_dir).markers(cell_id))
    return wal.publish(cell_channel(cell_id), "harness", KIND_DEATH, {
        "status": status, "archetype": archetype, "markers": markers,
        "reflection": "requested", "bundle": str(bundle_dir),
    })
