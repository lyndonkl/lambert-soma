"""Ladder PR-10: the soma WAL — store, cursors, membrane tools, S5 chaos."""

import json
import threading
import time

import pytest

from soma.wal import (
    CHANNEL_MAIN,
    WalExecutor,
    WalPublishAction,
    WalPublishTool,
    WalReadAction,
    WalReadTool,
    WalStore,
    cell_channel,
    new_ulid,
    wal_tool_specs,
    write_briefing,
)


@pytest.fixture
def store(tmp_path) -> WalStore:
    return WalStore(tmp_path / "wal.db")


def test_ulid_shape_and_monotonic():
    ids = [new_ulid() for _ in range(2000)]
    assert all(len(i) == 26 for i in ids)
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_publish_read_roundtrip(store):
    a = store.publish("main", "harness", "note", {"text": "one"})
    b = store.publish("main", "harness", "note", "two")
    events = store.read("main")
    assert [e["id"] for e in events] == [a, b]
    assert json.loads(events[0]["payload"]) == {"text": "one"}
    assert events[1]["payload"] == "two"
    assert store.count("main") == 2 and store.count() == 2


def test_cursor_advances_per_cell(store):
    for i in range(3):
        store.publish("main", "harness", "note", str(i))
    first = store.read_new("cell-a", "main", limit=2)
    second = store.read_new("cell-a", "main", limit=2)
    assert [e["payload"] for e in first] == ["0", "1"]
    assert [e["payload"] for e in second] == ["2"]
    assert store.read_new("cell-a", "main") == []
    # another cell has its own bookmark
    assert len(store.read_new("cell-b", "main")) == 3


def test_briefing_is_first_entry_of_task_log(store):
    write_briefing(store, "scout-1", "do the thing")
    store.publish(cell_channel("scout-1"), "scout-1", "note", "later")
    events = store.read(cell_channel("scout-1"))
    assert events[0]["kind"] == "briefing"
    assert json.loads(events[0]["payload"]) == {"text": "do the thing"}


def _executor(tmp_path, cell="scout-1", rate=30) -> WalExecutor:
    return WalExecutor(
        str(tmp_path / "wal.db"), cell,
        publish_channels=[cell_channel(cell)],
        read_channels=[cell_channel(cell), CHANNEL_MAIN],
        rate_per_minute=rate,
    )


def test_tools_enforce_subscriptions(tmp_path):
    ex = _executor(tmp_path)
    ok = ex(WalPublishAction(channel=cell_channel("scout-1"), message="hi"))
    assert not ok.is_error and "published" in ok.text
    bad = ex(WalPublishAction(channel="team:alpha", message="hi"))
    assert bad.is_error and "outside your membrane" in bad.text
    bad_read = ex(WalReadAction(channel="dialogue:9"))
    assert bad_read.is_error and "outside your membrane" in bad_read.text
    # main is readable, not publishable, in v0
    assert not ex(WalReadAction(channel=CHANNEL_MAIN)).is_error
    assert ex(WalPublishAction(channel=CHANNEL_MAIN, message="x")).is_error


def test_tool_read_uses_cursor_and_formats(tmp_path):
    ex = _executor(tmp_path)
    ex.store.publish(CHANNEL_MAIN, "harness", "note", {"text": "hello cell"})
    first = ex(WalReadAction(channel=CHANNEL_MAIN))
    assert "harness/note" in first.text and "hello cell" in first.text
    again = ex(WalReadAction(channel=CHANNEL_MAIN))
    assert "no new events" in again.text


def test_gossip_storm_is_throttled(tmp_path):
    ex = _executor(tmp_path, rate=5)
    chan = cell_channel("scout-1")
    results = [ex(WalPublishAction(channel=chan, message=f"m{i}")) for i in range(8)]
    assert [r.is_error for r in results] == [False] * 5 + [True] * 3
    assert "limit 5" in results[5].text and "batch" in results[5].text
    assert ex.store.count(chan) == 5  # nothing past the budget landed


def test_tool_specs_resolve_through_sdk_factories(tmp_path):
    specs = wal_tool_specs(tmp_path / "wal.db", "scout-1")
    assert [s.name for s in specs] == ["wal_publish", "wal_read"]
    pub = WalPublishTool.create(conv_state=None, **specs[0].params)[0]
    rd = WalReadTool.create(conv_state=None, **specs[1].params)[0]
    assert pub.annotations.readOnlyHint is False
    assert rd.annotations.readOnlyHint is True
    obs = pub.executor(WalPublishAction(channel=cell_channel("scout-1"), message="x"))
    assert not obs.is_error


def test_engine_mounts_wal_tools_for_the_cell(tmp_path, monkeypatch):
    """Both agent paths get wal_publish/wal_read scoped to the run's cell."""
    from types import SimpleNamespace

    from soma.config import SomaConfig
    from soma.engine import run_task
    from soma.profiles import bootstrap_profiles

    cfg = SomaConfig(
        profile_store_dir=str(tmp_path / "profiles"),
        runs_dir=str(tmp_path / "runs"),
        telemetry_db=str(tmp_path / "ledger.db"),
    )
    bootstrap_profiles(cfg, env={"OPENROUTER_API_KEY": "sk-test"})
    seen = {}

    def capture(agent, *a, **k):
        seen["tools"] = {t.name: t.params for t in agent.tools}
        return SimpleNamespace(
            send_message=lambda m: None, run=lambda: None,
            state=SimpleNamespace(execution_status=SimpleNamespace(value="finished")),
        )

    monkeypatch.setattr("soma.engine._make_conversation", capture)
    result = run_task("hello", cfg, visualize=False)
    assert {"wal_publish", "wal_read"} <= set(seen["tools"])
    params = seen["tools"]["wal_publish"]
    assert params["db_path"] == str(result.persistence_dir / "wal.db")
    assert params["publish_channels"] == [cell_channel(params["cell_id"])]
    assert CHANNEL_MAIN in params["read_channels"]


def test_S5_chaos_interleaved_writers_lose_nothing(tmp_path):
    """8 writers, 4 channels, 10,000 events: none lost, none doubled, ordered."""
    db = tmp_path / "wal.db"
    WalStore(db).close()
    writers, per_writer = 8, 1250
    channels = [f"team:{i}" for i in range(4)]
    errors: list[Exception] = []

    def work(w: int):
        s = WalStore(db)
        try:
            for n in range(per_writer):
                s.publish(channels[n % 4], f"w{w}", "note", {"w": w, "n": n})
        except Exception as exc:  # noqa: BLE001 — collected and asserted below
            errors.append(exc)
        finally:
            s.close()

    t0 = time.monotonic()
    threads = [threading.Thread(target=work, args=(w,)) for w in range(writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - t0

    s = WalStore(db)
    assert errors == []
    assert s.count() == writers * per_writer
    seen = set()
    for chan in channels:
        events = s.read(chan, limit=10_000)
        ids = [e["id"] for e in events]
        assert ids == sorted(ids) and len(set(ids)) == len(ids)
        for e in events:
            body = json.loads(e["payload"])
            seen.add((body["w"], body["n"]))
    assert len(seen) == writers * per_writer  # every (writer, seq) exactly once
    print(f"\nS5: {writers * per_writer} events / {elapsed:.2f}s "
          f"= {writers * per_writer / elapsed:.0f} ev/s, 0 errors")
