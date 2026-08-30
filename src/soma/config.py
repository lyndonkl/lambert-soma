"""soma.toml — project configuration.

One small file at the project root configures the harness: where runs
land, where LLM profiles live, and what each tier points at. Loading
never fails: a missing file yields pure defaults, so `soma doctor`
can always run and say what it found.

Tiers are open-ended: `[soma]` and `[local]` are the only reserved
sections; every other section declares a cloud tier named by its
header (`[reviewer]` → tier "reviewer"). `worker` and `lead` are
defaults that always exist because the harness binds them.

Search order: $SOMA_CONFIG if set, else soma.toml walking upward from
the working directory to the filesystem root.
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

from pydantic import BaseModel

CONFIG_FILENAME = "soma.toml"
CONFIG_ENV_VAR = "SOMA_CONFIG"
RESERVED_SECTIONS = ("soma", "local")
_TIER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class LocalTier(BaseModel):
    """The Apple-Silicon tier (ADR-005). Costs are zero by definition."""

    model: str = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit"
    base_url: str = "http://localhost:8000/v1"
    port: int = 8000


class CloudTier(BaseModel):
    """A cloud tier: just a model string. Fit-first — edit freely."""

    model: str


# Benchmark-picked 2026-08 (see PR #2): worker = top SWE-bench Verified
# per dollar; lead = strongest thinking model outside Anthropic/OpenAI.
DEFAULT_TIERS: dict[str, CloudTier] = {
    "worker": CloudTier(model="openrouter/deepseek/deepseek-v4-pro"),
    "lead": CloudTier(model="openrouter/moonshotai/kimi-k3"),
}


class SomaConfig(BaseModel):
    runs_dir: str = "runs"
    profile_store_dir: str = "~/.soma/profiles"
    local: LocalTier = LocalTier()
    tiers: dict[str, CloudTier] = DEFAULT_TIERS

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
    """Load soma.toml. Returns (config, path-or-None-if-defaults).

    Every section other than the reserved ones declares a cloud tier;
    declared tiers are merged over DEFAULT_TIERS (worker/lead always
    exist because the harness binds them by name).
    """
    path = _find_config_file(start or Path.cwd())
    if path is None:
        return SomaConfig(), None
    raw = tomllib.loads(path.read_text())
    data: dict = dict(raw.get("soma", {}))
    if "local" in raw:
        data["local"] = raw["local"]
    tiers = {k: v for k, v in raw.items() if k not in RESERVED_SECTIONS}
    for name, body in tiers.items():
        if not _TIER_NAME_RE.match(name):
            raise ValueError(
                f"{path}: [{name}] is not a valid tier name "
                "(lowercase letters, digits, '-' and '_' only)"
            )
        if not isinstance(body, dict) or "model" not in body:
            raise ValueError(
                f"{path}: [{name}] declares a cloud tier and needs a "
                'model = "provider/name" line'
            )
    if tiers:
        data["tiers"] = {**DEFAULT_TIERS, **tiers}
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

# Cloud tiers. Every other section in this file declares one — name it
# anything ([reviewer], [scout], ...) and archetypes bind it by name
# (`model: reviewer`). worker and lead always exist: the harness binds
# them. Fit-first policy: pick the model each seat deserves, then let
# the ledger report the bill. Comments give $/M tokens in/out, 2026-08.

[worker]  # agentic coding workhorse (SWE-bench Verified 80.6%)
model = "openrouter/deepseek/deepseek-v4-pro"  # $0.42 / $0.83

[lead]  # judgment seat: planning, delegation, audits (thinking model)
model = "openrouter/moonshotai/kimi-k3"  # $3.00 / $15.00

[analysis]  # data analysis, math-heavy interpretation (AIME26 99.2%)
model = "openrouter/z-ai/glm-5.2"  # $1.19 / $3.74

[summarizer]  # digests and condensation at cloud altitude
model = "openrouter/deepseek/deepseek-v4-flash-0731"  # $0.07 / $0.18

[classifier]  # labels and routing decisions, tiny outputs
model = "openrouter/qwen/qwen3.7-flash"  # $0.03 / $0.13

[intent]  # request -> structured intent parsing
model = "openrouter/z-ai/glm-5.3-flash"  # $0.08 / $0.25
"""
