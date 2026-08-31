"""PR-03: telemetry ledger. Fabricated bundles, no network."""

import json
import sqlite3

import pytest

from soma.config import SomaConfig
from soma.telemetry import config_hash, record_run, render_costs


@pytest.fixture
def cfg(tmp_path) -> SomaConfig:
    return SomaConfig(
        runs_dir=str(tmp_path / "runs"),
        telemetry_db=str(tmp_path / "ledger.db"),
        profile_store_dir=str(tmp_path / "profiles"),
    )


def make_bundle(cfg, run_id, usages, agent=None):
    """Write a minimal but shape-faithful base_state.json."""
    conv_id = f"conv-{run_id}"
    bundle = cfg.runs_path / run_id / conv_id
    bundle.mkdir(parents=True)
    metrics = {
        usage_id: {
            "model_name": model,
            "accumulated_cost": cost,
            "accumulated_token_usage": {
                "prompt_tokens": p, "completion_tokens": c,
                "cache_read_tokens": 7, "cache_write_tokens": 0,
            },
            "response_latencies": [{"latency": 1.0}] * calls,
        }
        for usage_id, (model, p, c, calls, cost) in usages.items()
    }
    state = {
        "id": conv_id,
        "agent": agent or {"llm": {"model": "m"}, "tools": ["terminal"]},
        "stats": {"usage_to_metrics": metrics},
    }
    (bundle / "base_state.json").write_text(json.dumps(state))
    return cfg.runs_path / run_id


def test_record_writes_run_and_call_rows(cfg):
    pdir = make_bundle(cfg, "r1", {
        "local": ("openai/mlx", 100, 10, 3, 0.0),
        "condenser": ("openai/mlx", 50, 5, 1, 0.0),
    })
    ok = record_run(cfg, "r1", "do a thing", "local", "/ws", "finished",
                    pdir, "2026-08-31T00:00:00Z")
    assert ok
    with sqlite3.connect(cfg.telemetry_db_path) as conn:
        run = conn.execute("SELECT * FROM runs").fetchone()
        calls = conn.execute(
            "SELECT usage_id, prompt_tokens, calls FROM llm_calls ORDER BY usage_id"
        ).fetchall()
    assert run[0] == "r1" and run[1] == "conv-r1" and run[5] == "finished"
    assert run[6] is not None and len(run[6]) == 12  # config hash present
    assert calls == [("condenser", 50, 1), ("local", 100, 3)]


def test_record_is_idempotent(cfg):
    pdir = make_bundle(cfg, "r1", {"local": ("m", 1, 1, 1, 0.0)})
    record_run(cfg, "r1", "t", "local", "/ws", "finished", pdir, "2026-08-31T00:00:00Z")
    record_run(cfg, "r1", "t", "local", "/ws", "finished", pdir, "2026-08-31T00:00:00Z")
    with sqlite3.connect(cfg.telemetry_db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0] == 1


def test_record_survives_missing_bundle(cfg):
    pdir = cfg.runs_path / "r-empty"
    pdir.mkdir(parents=True)
    ok = record_run(cfg, "r-empty", "t", "local", "/ws", "error:timeout",
                    pdir, "2026-08-31T00:00:00Z")
    assert ok  # run row still lands, with no llm rows
    with sqlite3.connect(cfg.telemetry_db_path) as conn:
        assert conn.execute("SELECT status FROM runs").fetchone()[0] == "error:timeout"
        assert conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0] == 0


def test_config_hash_stable_and_sensitive():
    a = {"llm": {"model": "x"}, "tools": ["t"]}
    assert config_hash(a) == config_hash(json.loads(json.dumps(a)))
    b = {"llm": {"model": "y"}, "tools": ["t"]}
    assert config_hash(a) != config_hash(b)


def test_render_costs_golden(cfg):
    p1 = make_bundle(cfg, "20260801-000001-aaaaaa", {
        "local": ("openai/mlx", 1000, 100, 4, 0.0),
        "condenser": ("openai/mlx", 200, 20, 1, 0.0),
    })
    p2 = make_bundle(cfg, "20260802-000002-bbbbbb", {
        "worker": ("openrouter/deepseek/deepseek-v4-pro", 5000, 500, 6, 0.0123),
    })
    record_run(cfg, "20260801-000001-aaaaaa", "t1", "local", "/ws", "finished",
               p1, "2026-08-01T00:00:00Z")
    record_run(cfg, "20260802-000002-bbbbbb", "t2", "worker", "/ws", "finished",
               p2, "2026-08-02T00:00:00Z")
    out = render_costs(cfg)
    expected = """\
RUN                      STATUS       TIER            COST
20260801-000001-aaaaaa   finished     local      $  0.0000
20260802-000002-bbbbbb   finished     worker     $  0.0123

per-brain totals (usage_id):
  condenser           200 in /       20 out tok     1 calls  $  0.0000  (1 runs)
  local             1,000 in /      100 out tok     4 calls  $  0.0000  (1 runs)
  worker            5,000 in /      500 out tok     6 calls  $  0.0123  (1 runs)"""
    body, _, reference = out.rpartition("\n\nmonth-to-date:")
    assert body == expected
    assert reference.startswith(" $")
    assert "of $200.00 reference" in reference


def test_render_costs_since_filter(cfg):
    p1 = make_bundle(cfg, "r-old", {"local": ("m", 1, 1, 1, 0.0)})
    p2 = make_bundle(cfg, "r-new", {"local": ("m", 1, 1, 1, 0.0)})
    record_run(cfg, "r-old", "t", "local", "/ws", "finished", p1, "2026-07-01T00:00:00Z")
    record_run(cfg, "r-new", "t", "local", "/ws", "finished", p2, "2026-08-30T00:00:00Z")
    out = render_costs(cfg, since="2026-08-01")
    assert "r-new" in out and "r-old" not in out


def test_render_costs_empty_ledger(cfg):
    assert "no runs recorded yet" in render_costs(cfg)


class _FinishedStub:
    def __init__(self):
        from types import SimpleNamespace

        self.state = SimpleNamespace(execution_status=SimpleNamespace(value="finished"))

    def send_message(self, message):
        pass

    def run(self):
        pass


def test_engine_records_run(cfg, monkeypatch):
    """run_task writes a ledger row even though the stub leaves no bundle."""
    from soma.profiles import bootstrap_profiles

    bootstrap_profiles(cfg, env={"OPENROUTER_API_KEY": "sk-test"})
    monkeypatch.setattr("soma.engine._make_conversation", lambda *a, **k: _FinishedStub())
    from soma.engine import run_task

    result = run_task("say hi", cfg, visualize=False)
    assert result.ok
    with sqlite3.connect(cfg.telemetry_db_path) as conn:
        row = conn.execute("SELECT run_id, status, tier FROM runs").fetchone()
    assert row == (result.run_id, "finished", "worker")
