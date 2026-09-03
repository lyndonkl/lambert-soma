"""PR-01: soma.toml loading."""

from pathlib import Path

import pytest

from soma.config import CONFIG_ENV_VAR, SomaConfig, load_config


def test_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    cfg, path = load_config(start=tmp_path)
    assert path is None
    assert cfg == SomaConfig()
    assert cfg.local.base_url == "http://localhost:8000/v1"
    assert set(cfg.tiers) == {"worker", "lead"}
    assert cfg.profile_store_path == Path("~/.soma/profiles").expanduser()


def test_full_file_parses(tmp_path, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    (tmp_path / "soma.toml").write_text(
        """
[soma]
runs_dir = "elsewhere/runs"
profile_store_dir = "~/alt-profiles"

[local]
model = "mlx-community/Qwen3-8B-4bit"
base_url = "http://localhost:9999/v1"
port = 9999

[worker]
model = "openrouter/x/y"

[lead]
model = "openrouter/a/b"
"""
    )
    cfg, path = load_config(start=tmp_path)
    assert path == tmp_path / "soma.toml"
    assert cfg.runs_dir == "elsewhere/runs"
    assert cfg.local.port == 9999
    assert cfg.tiers["worker"].model == "openrouter/x/y"
    assert cfg.tiers["lead"].model == "openrouter/a/b"
    assert cfg.profile_store_path == Path("~/alt-profiles").expanduser()


def test_upward_search(tmp_path, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    (tmp_path / "soma.toml").write_text("[worker]\nmodel = 'openrouter/found/it'\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    cfg, path = load_config(start=nested)
    assert path == tmp_path / "soma.toml"
    assert cfg.tiers["worker"].model == "openrouter/found/it"
    # unspecified sections fall back to defaults
    assert cfg.local.port == 8000


def test_custom_tier_merges_over_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    (tmp_path / "soma.toml").write_text("[reviewer]\nmodel = 'openrouter/z/r'\n")
    cfg, _ = load_config(start=tmp_path)
    # declared tier joins the defaults; worker/lead survive untouched
    assert set(cfg.tiers) == {"worker", "lead", "reviewer"}
    assert cfg.tiers["reviewer"].model == "openrouter/z/r"
    assert cfg.tiers["worker"] == SomaConfig().tiers["worker"]


def test_tier_section_requires_model(tmp_path, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    (tmp_path / "soma.toml").write_text("[reviewer]\ntemperature = 1\n")
    with pytest.raises(ValueError, match=r"\[reviewer\].*model"):
        load_config(start=tmp_path)


def test_tier_name_must_be_slug(tmp_path, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    (tmp_path / "soma.toml").write_text('["Bad Name"]\nmodel = "openrouter/x/y"\n')
    with pytest.raises(ValueError, match="not a valid tier name"):
        load_config(start=tmp_path)


def test_env_var_override(tmp_path, monkeypatch):
    special = tmp_path / "special.toml"
    special.write_text("[soma]\nruns_dir = 'env-runs'\n")
    (tmp_path / "soma.toml").write_text("[soma]\nruns_dir = 'ignored'\n")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(special))
    cfg, path = load_config(start=tmp_path)
    assert path == special
    assert cfg.runs_dir == "env-runs"


def test_tier_limits_parse_and_default(tmp_path, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    (tmp_path / "soma.toml").write_text(
        "[lead]\nmodel = 'openrouter/m/k'\nmax_output_tokens = 500000\ntimeout = 600\n"
        "[local]\nretries = 1\n"
    )
    cfg, _ = load_config(start=tmp_path)
    assert cfg.tiers["lead"].effective_limits == {
        "max_output_tokens": 500000, "timeout": 600, "retries": 10}  # retries defaulted
    assert cfg.tiers["worker"].effective_limits == {
        "max_output_tokens": 65536, "timeout": 2400, "retries": 10}
    assert cfg.local.effective_limits == {"max_output_tokens": 16384, "timeout": 600, "retries": 1}
