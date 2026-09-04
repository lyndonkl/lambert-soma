"""The soma WAL — Kind-2 logs, the only membrane between cells (PR-10).

One SQLite file per run (`runs/<run_id>/wal.db`) in WAL mode. Channels
are logical rows, not files: `main`, `team:<id>`, `dialogue:<id>`, and
one task log per cell, `cell:<cell_id>`. Every cell has a durable
cursor per channel it reads. Delivery is pull-based (PLAN §5.2).

What lands here for the cell level (Cell Protocol):
- B1: the harness writes the briefing as the FIRST entry of the cell's
  task log at birth. Birth is replayable from this file alone.
- Scoping: `wal_publish` / `wal_read` are membrane tools — a cell
  touches only channels it is subscribed to. v0 subscriptions: publish
  to its own task log; read its own task log and `main`.
- Spam guard: a per-cell publish rate limit, enforced from the DB so
  it holds across tool instances and processes.

Ids are ULIDs (26 chars, Crockford base32: 48-bit ms time + 80-bit
random), made monotonic within a process so a channel's id order is
its insertion order. No new dependencies.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openhands.sdk.tool import (
    Action,
    Observation,
    ToolAnnotations,
    ToolDefinition,
    ToolExecutor,
)
from pydantic import Field

WAL_FILENAME = "wal.db"
CHANNEL_MAIN = "main"
DEFAULT_RATE_PER_MINUTE = 30
BUSY_TIMEOUT_S = 5.0

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_LOCK = threading.Lock()
_last_ulid: list[int] = [0, 0]  # [ms, random80] for in-process monotonicity


def cell_channel(cell_id: str) -> str:
    return f"cell:{cell_id}"


def _b32(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(out))


def new_ulid() -> str:
    """ULID, monotonic within this process (same-ms ids strictly increase)."""
    with _ULID_LOCK:
        ms = int(time.time() * 1000)
        if ms <= _last_ulid[0]:
            ms = _last_ulid[0]
            rand = _last_ulid[1] + 1
        else:
            rand = int.from_bytes(os.urandom(10), "big")
        _last_ulid[0], _last_ulid[1] = ms, rand
    return _b32(ms, 10) + _b32(rand & ((1 << 80) - 1), 16)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class RateLimited(Exception):
    pass


class NotSubscribed(Exception):
    pass


class WalStore:
    """One run's WAL. Safe to open from many threads/processes at once."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            self.path, timeout=BUSY_TIMEOUT_S, check_same_thread=False
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, channel TEXT NOT NULL, author TEXT NOT NULL,
                kind TEXT NOT NULL, payload TEXT NOT NULL, ts TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS events_channel_id ON events(channel, id);
            CREATE TABLE IF NOT EXISTS cursors (
                cell TEXT NOT NULL, channel TEXT NOT NULL, last_id TEXT NOT NULL,
                PRIMARY KEY (cell, channel));
        """)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def publish(self, channel: str, author: str, kind: str, payload: Any) -> str:
        event_id = new_ulid()
        body = payload if isinstance(payload, str) else json.dumps(payload)
        # one transaction per event; SQLite serializes writers, busy-timeout retries
        with self._conn:
            self._conn.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?)",
                (event_id, channel, author, kind, body, _now_iso()),
            )
        return event_id

    def publish_limited(self, channel: str, author: str, kind: str, payload: Any,
                        rate_per_minute: int = DEFAULT_RATE_PER_MINUTE) -> str:
        """Publish unless `author` already spent its per-minute budget."""
        since = datetime.fromtimestamp(time.time() - 60, UTC).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        recent = self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE author = ? AND ts >= ?", (author, since)
        ).fetchone()[0]
        if recent >= rate_per_minute:
            raise RateLimited(
                f"{author} published {recent} events in the last minute "
                f"(limit {rate_per_minute}) — batch your updates, or wait"
            )
        return self.publish(channel, author, kind, payload)

    def read(self, channel: str, after: str | None = None, limit: int = 100) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, channel, author, kind, payload, ts FROM events "
            "WHERE channel = ? AND id > ? ORDER BY id LIMIT ?",
            (channel, after or "", limit),
        ).fetchall()
        keys = ("id", "channel", "author", "kind", "payload", "ts")
        return [dict(zip(keys, r, strict=True)) for r in rows]

    def read_new(self, cell: str, channel: str, limit: int = 100) -> list[dict]:
        """Events past this cell's cursor on `channel`; advances the cursor."""
        row = self._conn.execute(
            "SELECT last_id FROM cursors WHERE cell = ? AND channel = ?", (cell, channel)
        ).fetchone()
        events = self.read(channel, after=row[0] if row else None, limit=limit)
        if events:
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO cursors VALUES (?,?,?)",
                    (cell, channel, events[-1]["id"]),
                )
        return events

    def count(self, channel: str | None = None) -> int:
        if channel is None:
            return self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE channel = ?", (channel,)
        ).fetchone()[0]

    def channels(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT channel FROM events ORDER BY channel"
        ).fetchall()
        return [r[0] for r in rows]


# --- the membrane tools -------------------------------------------------

class WalPublishAction(Action):
    channel: str = Field(description="Channel to publish on — your own task log.")
    message: str = Field(description="What other cells or the harness should know.")
    event_kind: str = Field(default="note", description="note | discovery | help | done")


class WalReadAction(Action):
    channel: str = Field(description="Channel to read: your own task log or 'main'.")
    limit: int = Field(default=20, ge=1, le=200, description="Max new events to return.")


class WalObservation(Observation):
    pass


class WalExecutor(ToolExecutor):
    """Shared by both tools: opens the run's WAL, enforces scope + rate."""

    def __init__(self, db_path: str, cell_id: str, publish_channels: Sequence[str],
                 read_channels: Sequence[str], rate_per_minute: int):
        self.store = WalStore(db_path)
        self.cell_id = cell_id
        self.publish_channels = list(publish_channels)
        self.read_channels = list(read_channels)
        self.rate_per_minute = rate_per_minute

    def __call__(self, action, conversation=None):
        try:
            if isinstance(action, WalPublishAction):
                if action.channel not in self.publish_channels:
                    raise NotSubscribed(
                        f"you may publish only to {self.publish_channels}; "
                        f"'{action.channel}' is outside your membrane"
                    )
                event_id = self.store.publish_limited(
                    action.channel, self.cell_id, action.event_kind,
                    {"text": action.message}, self.rate_per_minute,
                )
                return WalObservation.from_text(f"published {event_id} to {action.channel}")
            if action.channel not in self.read_channels:
                raise NotSubscribed(
                    f"you may read only {self.read_channels}; "
                    f"'{action.channel}' is outside your membrane"
                )
            events = self.store.read_new(self.cell_id, action.channel, action.limit)
            if not events:
                return WalObservation.from_text(f"no new events on {action.channel}")
            lines = [f"[{e['id']}] {e['author']}/{e['kind']}: {e['payload']}" for e in events]
            return WalObservation.from_text("\n".join(lines))
        except (RateLimited, NotSubscribed) as exc:
            return WalObservation.from_text(str(exc), is_error=True)


def _build(cls, action_type, description: str, read_only: bool, params: dict) -> list:
    executor = WalExecutor(
        params["db_path"], params["cell_id"], params.get("publish_channels", ()),
        params.get("read_channels", ()),
        params.get("rate_per_minute", DEFAULT_RATE_PER_MINUTE),
    )
    return [cls(
        description=description, action_type=action_type,
        observation_type=WalObservation, executor=executor,
        annotations=ToolAnnotations(readOnlyHint=read_only, destructiveHint=False,
                                    idempotentHint=read_only, openWorldHint=False),
    )]


class WalPublishTool(ToolDefinition):
    @classmethod
    def create(cls, conv_state=None, **params):
        return _build(
            cls, WalPublishAction,
            "Publish an event to a channel you are subscribed to: note a discovery, "
            "ask for help, or announce completion to the harness.",
            False, params,
        )


class WalReadTool(ToolDefinition):
    @classmethod
    def create(cls, conv_state=None, **params):
        return _build(
            cls, WalReadAction,
            "Read new events since your last read on a channel you are subscribed to.",
            True, params,
        )


_registered = False


def register_wal_tools() -> None:
    global _registered
    if _registered:
        return
    from openhands.sdk import register_tool

    register_tool("wal_publish", WalPublishTool)
    register_tool("wal_read", WalReadTool)
    _registered = True


def wal_tool_specs(db_path: Path | str, cell_id: str,
                   rate_per_minute: int = DEFAULT_RATE_PER_MINUTE,
                   extra_channels: Sequence[str] = ()) -> list:
    """Tool specs for one cell: publish to its task log; read it and `main`.

    `extra_channels` widens both lists — e.g. the `dialogue:<id>` a cell
    was invited to (ladder PR-11). Default scoping is unchanged.
    """
    from openhands.sdk import Tool

    register_wal_tools()
    extras = list(extra_channels)
    params = {
        "db_path": str(db_path), "cell_id": cell_id,
        "publish_channels": [cell_channel(cell_id), *extras],
        "read_channels": [cell_channel(cell_id), CHANNEL_MAIN, *extras],
        "rate_per_minute": rate_per_minute,
    }
    return [Tool(name="wal_publish", params=params), Tool(name="wal_read", params=params)]


def open_run_wal(bundle_dir: Path) -> WalStore:
    return WalStore(Path(bundle_dir) / WAL_FILENAME)


def write_briefing(store: WalStore, cell_id: str, briefing: str) -> str:
    """B1: the briefing is the first entry in the cell's task log."""
    return store.publish(cell_channel(cell_id), "harness", "briefing", {"text": briefing})
