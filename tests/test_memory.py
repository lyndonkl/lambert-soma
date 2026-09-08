"""Ladder PR-12: memory points + death. No network."""

import json

from soma.memory import (
    KIND_DEATH,
    KIND_REMEMBER,
    RememberAction,
    RememberExecutor,
    StubMemoryStore,
    remember_tool_specs,
    write_death,
)
from soma.wal import WalStore, cell_channel


def test_stub_store_marks_and_reads_back_per_cell(tmp_path):
    store = StubMemoryStore(tmp_path)
    a = store.mark("scout-1", "scout", "the WAL lives in soma.wal", ["lesson"])
    store.mark("other-2", "other", "not mine", [])
    mine = store.markers("scout-1")
    assert [m["id"] for m in mine] == [a]
    assert mine[0]["archetype"] == "scout" and mine[0]["tags"] == ["lesson"]


def test_remember_executor_writes_marker_and_wal_event(tmp_path):
    wal_path = tmp_path / "wal.db"
    WalStore(wal_path).close()
    exe = RememberExecutor(str(tmp_path), str(wal_path), "scout-1", "scout")
    obs = exe(RememberAction(text="prefix caching needs a stable prompt", tags=["gotcha"]))
    assert not obs.is_error and "remembered" in obs.content[0].text
    events = WalStore(wal_path).read(cell_channel("scout-1"))
    assert [e["kind"] for e in events] == [KIND_REMEMBER]
    payload = json.loads(events[0]["payload"])
    assert payload["tags"] == ["gotcha"] and payload["marker"]
    assert StubMemoryStore(tmp_path).markers("scout-1")[0]["id"] == payload["marker"]


def test_tool_specs_are_scoped_to_the_cell(tmp_path):
    specs = remember_tool_specs(tmp_path, tmp_path / "wal.db", "scout-1", "scout")
    assert [t.name for t in specs] == ["remember"]
    assert specs[0].params["cell_id"] == "scout-1" and specs[0].params["archetype"] == "scout"


def test_write_death_carries_status_markers_and_reflection_request(tmp_path):
    wal = WalStore(tmp_path / "wal.db")
    StubMemoryStore(tmp_path).mark("scout-1", "scout", "one", [])
    write_death(wal, "scout-1", "finished", "scout", tmp_path)
    events = wal.read(cell_channel("scout-1"))
    assert [e["kind"] for e in events] == [KIND_DEATH]
    assert events[0]["author"] == "harness"  # X1: death is harness-side
    payload = json.loads(events[0]["payload"])
    assert payload == {"status": "finished", "archetype": "scout", "markers": 1,
                       "reflection": "requested", "bundle": str(tmp_path)}
