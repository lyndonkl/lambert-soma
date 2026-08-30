"""PR-01: tier profile bootstrap + doctor checks. No network involved."""

import pytest

from soma.config import SomaConfig
from soma.profiles import TIER_NAMES, bootstrap_profiles, check_profiles


@pytest.fixture
def cfg(tmp_path) -> SomaConfig:
    return SomaConfig(profile_store_dir=str(tmp_path / "profiles"))


def test_bootstrap_creates_three_profiles(cfg):
    report = bootstrap_profiles(cfg, env={"OPENROUTER_API_KEY": "sk-test"})
    assert sum(1 for line in report if line.startswith("created")) == 3
    from openhands.sdk import LLMProfileStore

    store = LLMProfileStore(cfg.profile_store_path)
    for name in TIER_NAMES:
        llm = store.load(name)
        assert llm.usage_id == name


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
    for name in TIER_NAMES:
        assert f"'{name}'" in messages


def test_doctor_flags_missing_cloud_key(cfg):
    bootstrap_profiles(cfg, env={})
    checks = check_profiles(cfg)
    infos = [m for ok, m in checks if ok is None]
    assert any("missing" in m for m in infos)
