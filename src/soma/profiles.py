"""LLM tier profiles: local / worker / lead.

The tiers live as named profiles in the SDK's LLMProfileStore, so an
archetype file can bind one with `model: worker` (ADR-006) and the
whole routing story stays data. `soma init` writes them; `soma doctor`
checks them.

Secrets: worker/lead read OPENROUTER_API_KEY from the environment at
init time and are saved with include_secrets=True into a user-local
store (never inside the repo). The local tier needs no key.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import SecretStr

from soma.config import SomaConfig

TIER_NAMES = ("local", "worker", "lead")
CLOUD_KEY_ENV = "OPENROUTER_API_KEY"


def _build_llm(name: str, cfg: SomaConfig, env: Mapping[str, str]):
    from openhands.sdk import LLM  # lazy: keeps `soma --help` fast

    if name == "local":
        return LLM(
            usage_id="local",
            model=f"openai/{cfg.local.model}",
            base_url=cfg.local.base_url,
            api_key=SecretStr("not-needed"),
            input_cost_per_token=0.0,
            output_cost_per_token=0.0,
        )
    key = env.get(CLOUD_KEY_ENV)
    tier = cfg.worker if name == "worker" else cfg.lead
    return LLM(
        usage_id=name,
        model=tier.model,
        api_key=SecretStr(key) if key else None,
    )


def bootstrap_profiles(
    cfg: SomaConfig,
    force: bool = False,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """Create the three tier profiles. Existing ones are kept unless force.

    Returns human-readable report lines.
    """
    from openhands.sdk import LLMProfileStore

    env = os.environ if env is None else env
    store_path = cfg.profile_store_path
    store_path.mkdir(parents=True, exist_ok=True)
    store = LLMProfileStore(store_path)
    existing = set(store.list())
    report: list[str] = []
    for name in TIER_NAMES:
        listed = f"{name}.json" in existing or name in existing
        if listed and not force:
            report.append(f"kept    {name} (exists; use --force to overwrite)")
            continue
        llm = _build_llm(name, cfg, env)
        store.save(name, llm, include_secrets=True)
        verb = "rewrote" if listed else "created"
        report.append(f"{verb} {name} -> {llm.model}")
    if not env.get(CLOUD_KEY_ENV):
        report.append(
            f"warning: {CLOUD_KEY_ENV} not set — worker/lead saved without a key"
        )
    return report


def check_profiles(cfg: SomaConfig) -> list[tuple[bool | None, str]]:
    """Doctor checks. Returns (ok, message); ok=None means informational."""
    from openhands.sdk import LLMProfileStore

    checks: list[tuple[bool | None, str]] = []
    store_path = cfg.profile_store_path
    if not store_path.is_dir():
        checks.append((False, f"profile store missing at {store_path} — run: soma init"))
        return checks
    store = LLMProfileStore(store_path)
    for name in TIER_NAMES:
        try:
            llm = store.load(name)
        except Exception as exc:  # noqa: BLE001 — doctor must survive any bad profile file
            checks.append((False, f"profile '{name}' not loadable ({exc}) — run: soma init"))
            continue
        if name == "local":
            ok = llm.base_url == cfg.local.base_url
            zero = (llm.input_cost_per_token or 0) == 0 and (llm.output_cost_per_token or 0) == 0
            checks.append((ok, f"profile 'local' -> {llm.model} @ {llm.base_url}"))
            checks.append((zero, "local tier costs pinned to zero (ledger honesty)"))
        else:
            has_key = llm.api_key is not None and bool(llm.api_key.get_secret_value())
            checks.append((True, f"profile '{name}' -> {llm.model}"))
            checks.append(
                (has_key if has_key else None,
                 f"'{name}' API key {'present' if has_key else 'missing — cloud calls will fail'}")
            )
    return checks
