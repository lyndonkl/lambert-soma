"""PR-05: archetype loader + validation. Fixture files incl. invalid ones."""

import pytest

from soma.archetypes import check_archetypes, load_archetypes
from soma.config import SomaConfig
from soma.profiles import bootstrap_profiles


@pytest.fixture
def cfg(tmp_path) -> SomaConfig:
    c = SomaConfig(profile_store_dir=str(tmp_path / "profiles"))
    bootstrap_profiles(c, env={"OPENROUTER_API_KEY": "sk-test"})
    return c


def write_archetype(project, name, model="worker", tools="[terminal]", extra=""):
    d = project / ".agents" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: test archetype\n"
        f"model: {model}\ntools: {tools}\n{extra}---\nPrompt body.\n"
    )


def test_seeds_load_with_levels_and_store(cfg, tmp_path):
    defs = load_archetypes(cfg, project_dir=tmp_path)
    assert {d.name for d in defs} == {"worker", "explorer", "reviewer"}
    for d in defs:
        assert d.level == "builtin"
        assert d.profile_store_dir == str(cfg.profile_store_path)
        assert d.system_prompt  # markdown body became the archetype core


def test_seed_soma_metadata_survives_loading(cfg, tmp_path):
    defs = {d.name: d for d in load_archetypes(cfg, project_dir=tmp_path)}
    assert defs["worker"].metadata.get("soma_version") == 1


def test_project_shadows_seed_and_is_noted(cfg, tmp_path):
    write_archetype(tmp_path, "worker", model="lead")
    defs = {d.name: d for d in load_archetypes(cfg, tmp_path)}
    assert defs["worker"].model == "lead"
    assert defs["worker"].level == "project"
    notes = [m for ok, m in check_archetypes(cfg, tmp_path) if ok is None]
    assert any("shadows" in m for m in notes)


def test_checks_healthy_on_seeds_alone(cfg, tmp_path):
    checks = check_archetypes(cfg, tmp_path)
    assert checks
    assert all(ok is not False for ok, _ in checks)


def test_unknown_tier_is_actionable(cfg, tmp_path):
    write_archetype(tmp_path, "custom", model="nonexistent")
    bad = [m for ok, m in check_archetypes(cfg, tmp_path) if ok is False]
    assert any("'custom'" in m and "soma init" in m for m in bad)


def test_unknown_tool_flagged(cfg, tmp_path):
    write_archetype(tmp_path, "custom", tools="[warp_drive]")
    bad = [m for ok, m in check_archetypes(cfg, tmp_path) if ok is False]
    assert any("warp_drive" in m for m in bad)


def test_unknown_soma_meta_key_flagged(cfg, tmp_path):
    write_archetype(tmp_path, "custom", extra="soma_wormhole: 1\n")
    bad = [m for ok, m in check_archetypes(cfg, tmp_path) if ok is False]
    assert any("soma_wormhole" in m for m in bad)


def test_nested_metadata_block_flagged(cfg, tmp_path):
    write_archetype(tmp_path, "custom", extra="metadata:\n  soma_version: 1\n")
    bad = [m for ok, m in check_archetypes(cfg, tmp_path) if ok is False]
    assert any("top level" in m for m in bad)


def test_inherit_model_is_informational(cfg, tmp_path):
    write_archetype(tmp_path, "custom", model="inherit")
    notes = [m for ok, m in check_archetypes(cfg, tmp_path) if ok is None]
    assert any("'custom'" in m and "inherits" in m for m in notes)


def test_duplicate_name_within_project_flagged(cfg, tmp_path):
    write_archetype(tmp_path, "twin")
    agents_dir = tmp_path / ".agents" / "agents"
    (agents_dir / "twin2.md").write_text("---\nname: twin\nmodel: worker\n---\nBody.\n")
    bad = [m for ok, m in check_archetypes(cfg, tmp_path) if ok is False]
    assert any("duplicate name 'twin'" in m for m in bad)


def test_broken_file_does_not_halt_loading(cfg, tmp_path):
    agents_dir = tmp_path / ".agents" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "broken.md").write_text("---\nname: [unclosed\n---\nbody")
    write_archetype(tmp_path, "good")
    assert "good" in {d.name for d in load_archetypes(cfg, tmp_path)}
