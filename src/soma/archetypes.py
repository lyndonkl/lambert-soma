"""Archetypes — soma's roles, in the SDK's file-agent format (ADR-006).

An archetype is a Markdown file with YAML frontmatter: `name`,
`description`, `model: <tier>` (a profile name — fit-first, every seat
named), `tools`, `skills`, and a reserved `metadata.soma_*` namespace.
The body is the archetype core prompt (layer 1 of B3).

soma ships NO roles: archetypes are the user's vocabulary (G9,
framework-not-app). Sources, project wins by name:
  1. the project's `.agents/agents/*.md` (the SDK's own convention)
  2. the user's library at `~/.agents/agents/*.md`

A project file sharing a user-library name deliberately shadows it:
per-project customization of a personal role. Validation is
pre-flight: it catches at `soma archetypes list` time what the SDK
factory would otherwise throw at cell-mint time.
"""

from __future__ import annotations

from pathlib import Path

from soma.config import SomaConfig

AGENTS_SUBDIR = Path(".agents") / "agents"
# The reserved namespace, v0: unknown soma_* keys are validation errors
# so future keys can be introduced without colliding with user data.
KNOWN_SOMA_META_KEYS = {"soma_version"}


def _load_dir(agents_dir: Path, level: str, cfg: SomaConfig) -> list:
    from openhands.sdk import load_agents_from_dir

    return [
        d.model_copy(update={
            "level": level,
            "profile_store_dir": str(cfg.profile_store_path),
        })
        for d in load_agents_from_dir(agents_dir)
    ]


def load_archetypes(cfg: SomaConfig, project_dir: Path | None = None) -> list:
    """All effective archetypes: project first, user library fills the gaps."""
    project = _load_dir((project_dir or Path.cwd()) / AGENTS_SUBDIR, "project", cfg)
    user = _load_dir(Path.home() / AGENTS_SUBDIR, "user", cfg)
    merged: dict[str, object] = {}
    for definition in [*project, *user]:
        merged.setdefault(definition.name, definition)
    return list(merged.values())


def check_archetypes(
    cfg: SomaConfig, project_dir: Path | None = None
) -> list[tuple[bool | None, str]]:
    """Doctor-style checks. (ok, msg); ok=None is informational."""
    from openhands.sdk import LLMProfileStore, list_registered_tools
    from openhands.tools import register_default_tools

    register_default_tools(enable_browser=False)
    registered_tools = set(list_registered_tools())
    store_path = cfg.profile_store_path
    profiles: set[str] = set()
    if store_path.is_dir():
        profiles = {
            n.removesuffix(".json") for n in LLMProfileStore(store_path).list()
        }

    project = _load_dir((project_dir or Path.cwd()) / AGENTS_SUBDIR, "project", cfg)
    user = _load_dir(Path.home() / AGENTS_SUBDIR, "user", cfg)
    checks: list[tuple[bool | None, str]] = []

    # collisions within one source are errors; project shadowing user is a feature
    for level, defs in (("project", project), ("user", user)):
        seen: set[str] = set()
        for d in defs:
            if d.name in seen:
                checks.append((False, f"{level} archetypes: duplicate name '{d.name}'"))
            seen.add(d.name)
    user_names = {d.name for d in user}
    for d in project:
        if d.name in user_names:
            checks.append((None, f"project '{d.name}' shadows your user-library archetype"))

    for d in load_archetypes(cfg, project_dir):
        if d.model in ("", "inherit"):
            checks.append((None, (
                f"archetype '{d.name}' inherits its caller's model — "
                "name a tier for fit-first accounting")))
        elif d.model.removesuffix(".json") not in profiles:
            checks.append((False, (
                f"archetype '{d.name}': model '{d.model}' has no profile at "
                f"{store_path} — declare the tier in soma.toml and run: soma init")))
        else:
            checks.append((True, f"archetype '{d.name}' -> tier '{d.model}'"))

        unknown_tools = set(d.tools) - registered_tools
        if unknown_tools:
            checks.append((False, (
                f"archetype '{d.name}': unknown tools {sorted(unknown_tools)} "
                f"(registered: {sorted(registered_tools)})")))

        bad_meta = {
            k for k in d.metadata if k.startswith("soma_")
        } - KNOWN_SOMA_META_KEYS
        if bad_meta:
            checks.append((False, (
                f"archetype '{d.name}': unknown soma_* metadata {sorted(bad_meta)} "
                f"(known: {sorted(KNOWN_SOMA_META_KEYS)})")))

        nested = d.metadata.get("metadata")
        if isinstance(nested, dict) and any(k.startswith("soma_") for k in nested):
            checks.append((False, (
                f"archetype '{d.name}': soma_* keys must sit at frontmatter "
                "top level, not nested under 'metadata:'")))
    return checks
