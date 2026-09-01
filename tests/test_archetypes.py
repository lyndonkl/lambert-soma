"""PR-05: archetype loader + validation. Fixture files incl. invalid ones.

soma ships no roles, so every archetype here is a test-authored file:
project-level under <tmp>/.agents/agents, user-level under a faked
home's ~/.agents/agents (Path.home is monkeypatched — tests must never
read the developer's real library).
"""

from pathlib import Path

import pytest

from soma.archetypes import check_archetypes, load_archetypes
from soma.config import SomaConfig
from soma.profiles import bootstrap_profiles


@pytest.fixture
def cfg(tmp_path) -> SomaConfig:
    c = SomaConfig(profile_store_dir=str(tmp_path / "profiles"))
    bootstrap_profiles(c, env={"OPENROUTER_API_KEY": "sk-test"})
    return c


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    return fake_home


def write_archetype(root, name, model="worker", tools="[terminal]",
                    extra="", filename=None):
    d = root / ".agents" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{filename or name}.md").write_text(
        f"---\nname: {name}\ndescription: test archetype\n"
        f"model: {model}\ntools: {tools}\n{extra}---\nPrompt body.\n"
    )


def test_no_shipped_roles(cfg, tmp_path, home):
    assert load_archetypes(cfg, project_dir=tmp_path / "proj") == []


def test_project_archetype_loads(cfg, tmp_path, home):
    proj = tmp_path / "proj"
    write_archetype(proj, "scout", model="local")
    defs = load_archetypes(cfg, project_dir=proj)
    assert [d.name for d in defs] == ["scout"]
    assert defs[0].level == "project"
    assert defs[0].model == "local"
    assert defs[0].profile_store_dir == str(cfg.profile_store_path)
    assert defs[0].system_prompt  # markdown body became the archetype core


def test_user_library_loads(cfg, tmp_path, home):
    write_archetype(home, "pal", model="lead")
    defs = load_archetypes(cfg, project_dir=tmp_path / "proj")
    assert [d.name for d in defs] == ["pal"]
    assert defs[0].level == "user"


def test_project_shadows_user_library(cfg, tmp_path, home):
    proj = tmp_path / "proj"
    write_archetype(home, "scout", model="lead")
    write_archetype(proj, "scout", model="local")
    defs = {d.name: d for d in load_archetypes(cfg, proj)}
    assert defs["scout"].level == "project"
    assert defs["scout"].model == "local"
    notes = [m for ok, m in check_archetypes(cfg, proj) if ok is None]
    assert any("shadows" in m for m in notes)


def test_soma_metadata_at_top_level_survives(cfg, tmp_path, home):
    proj = tmp_path / "proj"
    write_archetype(proj, "scout", extra="soma_version: 1\n")
    defs = load_archetypes(cfg, proj)
    assert defs[0].metadata.get("soma_version") == 1
    assert all(ok is not False for ok, _ in check_archetypes(cfg, proj))


def test_unknown_tier_is_actionable(cfg, tmp_path, home):
    proj = tmp_path / "proj"
    write_archetype(proj, "custom", model="nonexistent")
    bad = [m for ok, m in check_archetypes(cfg, proj) if ok is False]
    assert any("'custom'" in m and "soma init" in m for m in bad)


def test_unknown_tool_flagged(cfg, tmp_path, home):
    proj = tmp_path / "proj"
    write_archetype(proj, "custom", tools="[warp_drive]")
    bad = [m for ok, m in check_archetypes(cfg, proj) if ok is False]
    assert any("warp_drive" in m for m in bad)


def test_unknown_soma_meta_key_flagged(cfg, tmp_path, home):
    proj = tmp_path / "proj"
    write_archetype(proj, "custom", extra="soma_wormhole: 1\n")
    bad = [m for ok, m in check_archetypes(cfg, proj) if ok is False]
    assert any("soma_wormhole" in m for m in bad)


def test_nested_metadata_block_flagged(cfg, tmp_path, home):
    proj = tmp_path / "proj"
    write_archetype(proj, "custom", extra="metadata:\n  soma_version: 1\n")
    bad = [m for ok, m in check_archetypes(cfg, proj) if ok is False]
    assert any("top level" in m for m in bad)


def test_inherit_model_is_informational(cfg, tmp_path, home):
    proj = tmp_path / "proj"
    write_archetype(proj, "custom", model="inherit")
    notes = [m for ok, m in check_archetypes(cfg, proj) if ok is None]
    assert any("'custom'" in m and "inherits" in m for m in notes)


def test_duplicate_name_within_project_flagged(cfg, tmp_path, home):
    proj = tmp_path / "proj"
    write_archetype(proj, "twin")
    write_archetype(proj, "twin", filename="twin2")
    bad = [m for ok, m in check_archetypes(cfg, proj) if ok is False]
    assert any("duplicate name 'twin'" in m for m in bad)


def test_broken_file_does_not_halt_loading(cfg, tmp_path, home):
    proj = tmp_path / "proj"
    agents_dir = proj / ".agents" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "broken.md").write_text("---\nname: [unclosed\n---\nbody")
    write_archetype(proj, "good")
    assert "good" in {d.name for d in load_archetypes(cfg, proj)}
