"""Cell Protocol conformance — cell-in-a-box v0 (PR-04).

Every test cites the rule ids it enforces (docs/protocols/cell.md §8).
Rules whose mechanisms land on later rungs appear as explicit skips:
the scoreboard is the contract made visible, and it grows as the
ladder climbs — a rule is never silently unenforced.

The live crash-resume check needs the local server; it skips honestly
when the server is down and runs in the PR proof.
"""

import json
import urllib.request
import uuid
from types import SimpleNamespace

import pytest

from soma.config import SomaConfig
from soma.engine import resume_run, run_task
from soma.profiles import bootstrap_profiles


def _local_server_up() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:8000/v1/models", timeout=1):
            return True
    except OSError:
        return False


requires_local = pytest.mark.skipif(
    not _local_server_up(), reason="live check: local server on :8000 required"
)


@pytest.fixture
def cfg(tmp_path) -> SomaConfig:
    c = SomaConfig(
        profile_store_dir=str(tmp_path / "profiles"),
        runs_dir=str(tmp_path / "runs"),
        telemetry_db=str(tmp_path / "ledger.db"),
    )
    bootstrap_profiles(c, env={"OPENROUTER_API_KEY": "sk-test"})
    return c


class _Stub:
    def __init__(self):
        self.sent: list[str] = []
        self.state = SimpleNamespace(execution_status=SimpleNamespace(value="finished"))

    def send_message(self, message):
        self.sent.append(message)

    def run(self):
        pass


# --- BIRTH ---------------------------------------------------------------

def test_B2_briefing_is_engine_logs_first_message(cfg, monkeypatch):
    stub = _Stub()
    monkeypatch.setattr("soma.engine._make_conversation", lambda *a, **k: stub)
    run_task("the briefing", cfg, visualize=False)
    assert stub.sent == ["the briefing"]  # B2: opening message == briefing


def test_B1_briefing_opens_task_log(cfg, monkeypatch):
    """B1: the briefing is the FIRST entry in the cell's task log (Kind-2)."""
    from soma.wal import WAL_FILENAME, WalStore

    stub = _Stub()
    monkeypatch.setattr("soma.engine._make_conversation", lambda *a, **k: stub)
    result = run_task("the briefing", cfg, visualize=False)
    store = WalStore(result.persistence_dir / WAL_FILENAME)
    task_logs = [c for c in store.channels() if c.startswith("cell:")]
    assert len(task_logs) == 1
    first = store.read(task_logs[0])[0]
    assert first["kind"] == "briefing" and first["author"] == "harness"
    assert json.loads(first["payload"]) == {"text": "the briefing"}


def test_C4_B3_system_suffix_is_core_plus_overlay_only(cfg, tmp_path, monkeypatch):
    """B3 stable prefix + the suffix half of C4.

    The system suffix is exactly archetype core + task overlay — the
    briefing never enters it (it is the first user message, B2). The
    log-digest half of C4 arms with the WAL (ladder PR-10).
    """
    from pathlib import Path

    from soma.cells import TASK_MODE_OVERLAY, find_archetype, mint_agent

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    proj = tmp_path / "proj"
    agents_dir = proj / ".agents" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "scout.md").write_text(
        "---\nname: scout\nmodel: local\ntools: [terminal]\n---\nScout core.\n"
    )
    from openhands.sdk import Agent, Tool

    definition = find_archetype(cfg, "scout", proj)
    agent = mint_agent(cfg, definition)
    base = Agent(llm=agent.llm, tools=[Tool(name="terminal")]).static_system_message
    # the equality IS the isolation proof: base preset + core + overlay,
    # nothing else — no briefing, no logs, no harness extras hiding in it
    assert agent.static_system_message == f"{base}\n\nScout core.\n\n{TASK_MODE_OVERLAY}"


# --- TASK ----------------------------------------------------------------

@pytest.mark.skip(reason="T1: scoped board tools arrive PR-08")
def test_T1_idle_without_claimed_bead():
    ...


@pytest.mark.skip(reason="T2: log notifications arrive rung 2 (scheduler+inbox)")
def test_T2_notification_does_not_rebuild_cell():
    ...


# --- DONE ----------------------------------------------------------------

@pytest.mark.skip(reason="N1+N2: Stop-hook discipline arrives PR-09")
def test_N1_N2_finish_blocked_while_bead_open():
    ...


# --- DIALOGUE / TEAM AWARENESS ------------------------------------------

@pytest.mark.skip(reason="D2+D5: dialogue brokering arrives rung 2 (PR-18)")
def test_D2_D5_dialogue_park_unpark_and_summary_injection():
    ...


@pytest.mark.skip(reason="C6-C8: team_roster/team_goal arrive rung 2 (team.md)")
def test_C6_C7_C8_roster_and_goal_queries_opaque_and_solo_safe():
    ...


# --- DEATH / RESUME ------------------------------------------------------

def test_X4_bundle_and_ledger_survive_any_run(cfg, monkeypatch):
    import sqlite3

    stub = _Stub()
    monkeypatch.setattr("soma.engine._make_conversation", lambda *a, **k: stub)
    result = run_task("t", cfg, visualize=False)
    assert result.persistence_dir.is_dir()  # X4: bundle survives
    with sqlite3.connect(cfg.telemetry_db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


def test_R1_resume_reconstructs_same_conversation(cfg, monkeypatch):
    conv_id = str(uuid.uuid4())
    bundle = cfg.runs_path / "r-dead" / conv_id.replace("-", "")
    bundle.mkdir(parents=True)
    (bundle / "base_state.json").write_text(json.dumps({
        "id": conv_id,
        "workspace": {"working_dir": str(cfg.runs_path)},
        "agent": {"llm": {"model": "m"}},
        "stats": {"usage_to_metrics": {}},
    }))
    seen = {}

    def capture(agent, workspace, persistence_dir, max_iterations, visualize,
                conversation_id=None):
        seen["conversation_id"] = conversation_id
        return _Stub()

    monkeypatch.setattr("soma.engine._make_conversation", capture)
    result = resume_run("r-dead", cfg, visualize=False)
    assert seen["conversation_id"] == uuid.UUID(conv_id)  # R1: same identity
    assert result.run_id == "r-dead"


def test_R1_missing_bundle_is_actionable(cfg):
    with pytest.raises(ValueError, match="nothing to resume"):
        resume_run("never-existed", cfg)


def test_R2_resume_does_not_resend_a_message(cfg, monkeypatch):
    conv_id = str(uuid.uuid4())
    bundle = cfg.runs_path / "r-dead2" / conv_id.replace("-", "")
    bundle.mkdir(parents=True)
    (bundle / "base_state.json").write_text(json.dumps({
        "id": conv_id,
        "workspace": {"working_dir": str(cfg.runs_path)},
        "agent": {},
        "stats": {},
    }))
    stub = _Stub()
    monkeypatch.setattr("soma.engine._make_conversation", lambda *a, **k: stub)
    resume_run("r-dead2", cfg, visualize=False)
    assert stub.sent == []  # R2: continue, never restart with a fresh message


@requires_local
def test_R1_R2_X4_live_crash_resume(tmp_path):
    """Kill mid-task (iteration cap), resume, prove continuation not restart."""
    import sqlite3

    cfg = SomaConfig(
        runs_dir=str(tmp_path / "runs"),
        telemetry_db=str(tmp_path / "ledger.db"),
        profile_store_dir="~/.soma/profiles",  # real local profile
    )
    ws = tmp_path / "ws"
    ws.mkdir()
    task = ("Run these five commands, one terminal command per step, "
            "in order: echo a; echo b; echo c; echo d; echo e. "
            "Each echo must be its own separate step. Then finish.")
    dead = run_task(task, cfg, tier="local", workspace=ws,
                    max_iterations=3, visualize=False)
    assert not dead.ok  # died mid-task by design
    events_before = len(list(dead.persistence_dir.glob("*/events/*.json")))

    revived = resume_run(dead.run_id, cfg, tier="local",
                         max_iterations=30, visualize=False)
    events_after = len(list(revived.persistence_dir.glob("*/events/*.json")))
    system_prompts = [
        f for f in revived.persistence_dir.glob("*/events/*.json")
        if json.loads(f.read_text()).get("kind") == "SystemPromptEvent"
    ]
    assert revived.ok, f"resume ended {revived.status}: {revived.detail}"
    assert events_after > events_before          # R1: continued
    assert len(system_prompts) == 1              # R2: no re-init, no restart
    with sqlite3.connect(cfg.telemetry_db_path) as conn:
        rows = conn.execute(
            "SELECT status FROM runs WHERE run_id = ?", (dead.run_id,)
        ).fetchall()
    assert rows == [("finished",)]               # X4/R1: one row, updated
