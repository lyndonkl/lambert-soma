"""LLM tier profiles — one per tier declared in soma.toml.

The tiers live as named profiles in the SDK's LLMProfileStore, so an
archetype file can bind one with `model: worker` (ADR-006) and the
whole routing story stays data. `soma init` writes one profile per
declared tier; `soma doctor` scans the store and checks whatever is
actually there. `local` is the one reserved tier (built against the
local server, costs pinned to zero); everything else is a cloud tier.

Secrets: cloud tiers read OPENROUTER_API_KEY from the environment at
init time and are saved with include_secrets=True into a user-local
store (never inside the repo). The local tier needs no key.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import SecretStr

from soma.config import SomaConfig

CLOUD_KEY_ENV = "OPENROUTER_API_KEY"


def tier_names(cfg: SomaConfig) -> tuple[str, ...]:
    """Every tier this config declares: local plus the cloud tiers."""
    return ("local", *cfg.tiers)


def _limit_kwargs(limits: Mapping[str, int]) -> dict:
    return {
        "max_output_tokens": limits["max_output_tokens"],
        "timeout": limits["timeout"],
        "num_retries": limits["retries"],
    }


def _build_llm(name: str, cfg: SomaConfig, env: Mapping[str, str],
               existing_key: str | None = None):
    from openhands.sdk import LLM  # lazy: keeps `soma --help` fast

    if name == "local":
        return LLM(
            usage_id="local",
            model=f"openai/{cfg.local.model}",
            base_url=cfg.local.base_url,
            api_key=SecretStr("not-needed"),
            input_cost_per_token=0.0,
            output_cost_per_token=0.0,
            **_limit_kwargs(cfg.local.effective_limits),
        )
    # env wins; else keep the key a previous init baked in (a --force from a
    # shell without the env var must never strip credentials)
    key = env.get(CLOUD_KEY_ENV) or existing_key
    tier = cfg.tiers[name]
    return LLM(
        usage_id=name,
        model=tier.model,
        api_key=SecretStr(key) if key else None,
        **_limit_kwargs(tier.effective_limits),
    )


def _existing_key(store, name: str) -> str | None:
    try:
        llm = store.load(name)
    except Exception:  # noqa: BLE001 — a bad old profile just means no key to keep
        return None
    return llm.api_key.get_secret_value() if llm.api_key else None


def bootstrap_profiles(
    cfg: SomaConfig,
    force: bool = False,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """Create one profile per declared tier. Existing ones are kept unless force.

    Returns human-readable report lines.
    """
    from openhands.sdk import LLMProfileStore

    env = os.environ if env is None else env
    store_path = cfg.profile_store_path
    store_path.mkdir(parents=True, exist_ok=True)
    store = LLMProfileStore(store_path)
    existing = set(store.list())
    report: list[str] = []
    for name in tier_names(cfg):
        listed = f"{name}.json" in existing or name in existing
        if listed and not force:
            report.append(f"kept    {name} (exists; use --force to overwrite)")
            continue
        existing_key = _existing_key(store, name) if listed else None
        llm = _build_llm(name, cfg, env, existing_key)
        store.save(name, llm, include_secrets=True)
        verb = "rewrote" if listed else "created"
        report.append(f"{verb} {name} -> {llm.model}")
    if not env.get(CLOUD_KEY_ENV):
        report.append(
            f"warning: {CLOUD_KEY_ENV} not set — cloud tiers "
            f"({', '.join(cfg.tiers)}) keep any previously baked key, else none"
        )
    return report


def check_profiles(cfg: SomaConfig) -> list[tuple[bool | None, str]]:
    """Doctor checks. Returns (ok, message); ok=None means informational.

    Scans the store itself: declared tiers must have a loadable profile,
    and hand-added profiles (in the store but not in soma.toml) are
    checked too — archetypes can bind those by name just the same.
    """
    from openhands.sdk import LLMProfileStore

    checks: list[tuple[bool | None, str]] = []
    store_path = cfg.profile_store_path
    if not store_path.is_dir():
        checks.append((False, f"profile store missing at {store_path} — run: soma init"))
        return checks
    store = LLMProfileStore(store_path)
    present = {n.removesuffix(".json") for n in store.list()}
    declared = tier_names(cfg)
    extras = sorted(present - set(declared))
    for name in [*declared, *extras]:
        if name not in present:
            checks.append((False, f"tier '{name}' in soma.toml but no profile — run: soma init"))
            continue
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
        if name in extras:
            checks.append((None, f"profile '{name}' not in soma.toml (hand-added — still bindable)"))
    return checks
