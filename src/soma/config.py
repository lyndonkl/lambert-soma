"""soma.toml — project configuration.

One small file at the project root configures the harness: where runs
land, where LLM profiles live, and what each tier points at. Loading
never fails: a missing file yields pure defaults, so `soma doctor`
can always run and say what it found.

Search order: $SOMA_CONFIG if set, else soma.toml walking upward from
the working directory to the filesystem root.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel

CONFIG_FILENAME = "soma.toml"
CONFIG_ENV_VAR = "SOMA_CONFIG"


class LocalTier(BaseModel):
    """The Apple-Silicon tier (ADR-005). Costs are zero by definition."""

    model: str = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit"
    base_url: str = "http://localhost:8000/v1"
    port: int = 8000


class CloudTier(BaseModel):
    """A cloud tier: just a model string. Fit-first — edit freely."""

    model: str


class SomaConfig(BaseModel):
    runs_dir: str = "runs"
    profile_store_dir: str = "~/.soma/profiles"
    local: LocalTier = LocalTier()
    worker: CloudTier = CloudTier(model="openrouter/qwen/qwen3-coder")
    lead: CloudTier = CloudTier(model="openrouter/anthropic/claude-sonnet-4.5")

    @property
    def profile_store_path(self) -> Path:
        return Path(self.profile_store_dir).expanduser()

    @property
    def runs_path(self) -> Path:
        return Path(self.runs_dir).expanduser()


def _find_config_file(start: Path) -> Path | None:
    env = os.environ.get(CONFIG_ENV_VAR)
    if env:
        p = Path(env).expanduser()
        return p if p.is_file() else None
    for directory in [start, *start.parents]:
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_config(start: Path | None = None) -> tuple[SomaConfig, Path | None]:
    """Load soma.toml. Returns (config, path-or-None-if-defaults)."""
    path = _find_config_file(start or Path.cwd())
    if path is None:
        return SomaConfig(), None
    raw = tomllib.loads(path.read_text())
    data: dict = dict(raw.get("soma", {}))
    for section in ("local", "worker", "lead"):
        if section in raw:
            data[section] = raw[section]
    return SomaConfig(**data), path


STARTER_TOML = """\
# soma.toml — lambert-soma harness configuration.
# Delete any line to fall back to its default.

[soma]
runs_dir = "runs"
profile_store_dir = "~/.soma/profiles"

# The local tier (Apple Silicon, ADR-005). Zero cost by definition.
[local]
model = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit"
base_url = "http://localhost:8000/v1"
port = 8000

# Cloud tiers. Fit-first policy: pick the model each job deserves,
# then let the ledger report the bill. EDIT these to taste.
[worker]
model = "openrouter/qwen/qwen3-coder"

[lead]
model = "openrouter/anthropic/claude-sonnet-4.5"
"""
