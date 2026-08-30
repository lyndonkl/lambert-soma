"""PR-01: tier profile bootstrap + doctor checks. No network involved."""

import pytest

from soma.config import SomaConfig
from soma.profiles import bootstrap_profiles, check_profiles, tier_names


@pytest.fixture
def cfg(tmp_path) -> SomaConfig:
    return SomaConfig(profile_store_dir=str(tmp_path / "profiles"))


def test_bootstrap_creates_all_declared_tiers(cfg):
    report = bootstrap_profiles(cfg, env={"OPENROUTER_API_KEY": "sk-test"})
    assert sum(1 for line in report if line.startswith("created")) == len(tier_names(cfg))
    from openhands.sdk import LLMProfileStore

    store = LLMProfileStore(cfg.profile_store_path)
    for name in tier_names(cfg):
        llm = store.load(name)
        assert llm.usage_id == name


def test_custom_tier_gets_a_profile(tmp_path):
    cfg = SomaConfig(
        profile_store_dir=str(tmp_path / "profiles"),
        tiers={"reviewer": {"model": "openrouter/z/r"}},
    )
    bootstrap_profiles(cfg, env={"OPENROUTER_API_KEY": "sk-test"})
    from openhands.sdk import LLMProfileStore

    reviewer = LLMProfileStore(cfg.profile_store_path).load("reviewer")
    assert reviewer.usage_id == "reviewer"
    assert reviewer.model == "openrouter/z/r"


def test_local_profile_shape(cfg):
    bootstrap_profiles(cfg, env={})
    from openhands.sdk import LLMProfileStore

    local = LLMProfileStore(cfg.profile_store_path).load("local")
    assert local.base_url == cfg.local.base_url
    assert local.model.startswith("openai/")
    assert (local.input_cost_per_token or 0) == 0
    assert (local.output_cost_per_token or 0) == 0


def test_cloud_key_roundtrip(cfg):
    bootstrap_profiles(cfg, env={"OPENROUTER_API_KEY": "sk-roundtrip"})
    from openhands.sdk import LLMProfileStore

    worker = LLMProfileStore(cfg.profile_store_path).load("worker")
    assert worker.api_key is not None
    assert worker.api_key.get_secret_value() == "sk-roundtrip"


def test_missing_key_warns_but_creates(cfg):
    report = bootstrap_profiles(cfg, env={})
    assert any(line.startswith("warning") for line in report)
    assert sum(1 for line in report if line.startswith("created")) == 3


def test_idempotent_then_force(cfg):
    bootstrap_profiles(cfg, env={"OPENROUTER_API_KEY": "sk-1"})
    second = bootstrap_profiles(cfg, env={"OPENROUTER_API_KEY": "sk-2"})
    assert sum(1 for line in second if line.startswith("kept")) == 3
    forced = bootstrap_profiles(cfg, force=True, env={"OPENROUTER_API_KEY": "sk-2"})
    assert sum(1 for line in forced if line.startswith("rewrote")) == 3
    from openhands.sdk import LLMProfileStore

    worker = LLMProfileStore(cfg.profile_store_path).load("worker")
    assert worker.api_key is not None
    assert worker.api_key.get_secret_value() == "sk-2"


def test_doctor_checks_missing_store(cfg):
    checks = check_profiles(cfg)
    assert len(checks) == 1
    ok, message = checks[0]
    assert ok is False
    assert "soma init" in message


def test_doctor_checks_healthy_store(cfg):
    bootstrap_profiles(cfg, env={"OPENROUTER_API_KEY": "sk-test"})
    checks = check_profiles(cfg)
    assert all(ok is not False for ok, _ in checks)
    messages = " | ".join(m for _, m in checks)
    for name in tier_names(cfg):
        assert f"'{name}'" in messages


def test_doctor_flags_missing_cloud_key(cfg):
    bootstrap_profiles(cfg, env={})
    checks = check_profiles(cfg)
    infos = [m for ok, m in checks if ok is None]
    assert any("missing" in m for m in infos)


def test_doctor_flags_declared_but_missing_profile(cfg):
    bootstrap_profiles(cfg, env={"OPENROUTER_API_KEY": "sk-test"})
    wider = SomaConfig(
        profile_store_dir=cfg.profile_store_dir,
        tiers={**cfg.tiers, "reviewer": {"model": "openrouter/z/r"}},
    )
    checks = check_profiles(wider)
    bad = [m for ok, m in checks if ok is False]
    assert any("'reviewer'" in m and "soma init" in m for m in bad)


def test_doctor_notes_hand_added_profile(cfg):
    bootstrap_profiles(cfg, env={"OPENROUTER_API_KEY": "sk-test"})
    from openhands.sdk import LLM, LLMProfileStore

    store = LLMProfileStore(cfg.profile_store_path)
    store.save("scout", LLM(usage_id="scout", model="openrouter/s/s"))
    checks = check_profiles(cfg)
    infos = [m for ok, m in checks if ok is None]
    assert any("'scout'" in m and "hand-added" in m for m in infos)
    # hand-added profiles are noted, never failed
    assert all(ok is not False for ok, _ in checks)
