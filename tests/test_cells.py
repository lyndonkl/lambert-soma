"""Ladder PR-06: cell factory + stable-prefix layering. No network."""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from soma.cells import TASK_MODE_OVERLAY, find_archetype, layered_suffix, mint_agent, new_cell_id
from soma.config import SomaConfig
from soma.profiles import bootstrap_profiles


@pytest.fixture
def cfg(tmp_path) -> SomaConfig:
    c = SomaConfig(
        profile_store_dir=str(tmp_path / "profiles"),
        runs_dir=str(tmp_path / "runs"),
        telemetry_db=str(tmp_path / "ledger.db"),
    )
    bootstrap_profiles(c, env={"OPENROUTER_API_KEY": "sk-test"})
    return c


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    return fake_home


def write_archetype(root, name, model="worker", tools="[terminal]", body="Role core."):
    d = root / ".agents" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: test\nmodel: {model}\n"
        f"tools: {tools}\n---\n{body}\n"
    )


def test_layered_suffix_is_core_then_overlay(cfg, tmp_path, home):
    proj = tmp_path / "proj"
    write_archetype(proj, "scout", body="I am the scout core.")
    d = find_archetype(cfg, "scout", proj)
    suffix = layered_suffix(d)
    assert suffix.startswith("I am the scout core.")
    assert suffix.endswith(TASK_MODE_OVERLAY)
    # stable prefix: same archetype -> byte-identical suffix, every time
    assert suffix == layered_suffix(find_archetype(cfg, "scout", proj))


def test_mint_agent_wiring(cfg, tmp_path, home):
    proj = tmp_path / "proj"
    write_archetype(proj, "scout", model="local", tools="[terminal]")
    agent = mint_agent(cfg, find_archetype(cfg, "scout", proj))
    assert agent.llm.usage_id == "agent:scout"
    assert agent.llm.model.startswith("openai/")  # the local tier's model
    assert agent.llm.timeout == 600 and agent.llm.num_retries == 2
    names = {t.name for t in agent.tools}
    assert "terminal" in names and "file_editor" not in names  # the role's own tools
    from soma.beads import BEADS_TOOL_NAMES

    assert set(BEADS_TOOL_NAMES) <= names  # every cell gets its scoped board tools (T3)
    assert agent.condenser.llm.usage_id == "condenser"
    # layers composed into the STATIC prompt (EXP-003): base preset,
    # then core + overlay as the archetype-stable tail
    assert agent.static_system_message.endswith(
        layered_suffix(find_archetype(cfg, "scout", proj))
    )
    assert len(agent.static_system_message) > 10_000  # preset base still present


def test_mint_requires_a_named_tier(cfg, tmp_path, home):
    proj = tmp_path / "proj"
    write_archetype(proj, "drifty", model="inherit")
    with pytest.raises(ValueError, match="name their seat"):
        mint_agent(cfg, find_archetype(cfg, "drifty", proj))


def test_mint_missing_profile_is_actionable(cfg, tmp_path, home):
    proj = tmp_path / "proj"
    write_archetype(proj, "ghosty", model="ghost")
    with pytest.raises(ValueError, match="soma init"):
        mint_agent(cfg, find_archetype(cfg, "ghosty", proj))


def test_find_archetype_unknown_lists_available(cfg, tmp_path, home):
    proj = tmp_path / "proj"
    write_archetype(proj, "scout")
    with pytest.raises(ValueError, match="available: scout"):
        find_archetype(cfg, "nope", proj)


def test_cell_id_carries_archetype():
    assert new_cell_id("scout").startswith("scout-")


class _Stub:
    def __init__(self):
        self.sent: list[str] = []
        self.state = SimpleNamespace(execution_status=SimpleNamespace(value="finished"))

    def send_message(self, message):
        self.sent.append(message)

    def run(self):
        pass


def test_run_task_as_archetype_meters_its_seat(cfg, tmp_path, home, monkeypatch):
    from soma.engine import run_task

    proj = tmp_path / "proj"
    proj.mkdir()
    write_archetype(proj, "scout", model="local")
    stub = _Stub()
    monkeypatch.setattr("soma.engine._make_conversation", lambda *a, **k: stub)
    result = run_task("the briefing", cfg, archetype="scout",
                      workspace=proj, visualize=False)
    assert result.ok
    assert stub.sent == ["the briefing"]  # B2: briefing is the first message
    with sqlite3.connect(cfg.telemetry_db_path) as conn:
        row = conn.execute("SELECT tier FROM runs").fetchone()
    assert row == ("local",)  # ledger records the seat the role actually used
