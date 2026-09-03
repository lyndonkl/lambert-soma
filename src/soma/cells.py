"""Cell identity + the factory that turns an archetype file into an Agent.

The factory is the hand-off point of ladder PR-05 -> PR-06: a loaded
AgentDefinition (a role file) becomes a real SDK Agent. Wiring:

- the archetype's `model: <tier>` profile becomes the agent LLM,
  rebadged `usage_id=agent:<name>` so the ledger meters per role
- prompt layering is stable-prefix (Cell Protocol B3): the system
  suffix is exactly archetype core + task-mode overlay, identical for
  every cell of that archetype; the briefing NEVER enters the system
  prompt — it arrives as the first user message (B2)
- condenser rides the local tier under its own ledger name, same as
  the proto-cell engine

The `Cell` record is v0 identity only (id, archetype, run). The full
registry with lifecycle statuses is ladder PR-14.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from soma.config import SomaConfig
from soma.engine import ENGINE_LLM_RETRIES, ENGINE_LLM_TIMEOUT

# Task-mode overlay (B3 layer 2). Harness-owned protocol text, not role
# content: the duties every task cell has regardless of archetype.
TASK_MODE_OVERLAY = """<soma:mode:task>
This is a task activity (Cell Protocol v0). Work only the briefing
that arrives as the first user message. When it is complete and
verified, finish explicitly (rule N1) — never infer completion from
summaries and never redo work you already verified (EXP-002).
</soma:mode:task>"""


@dataclass
class Cell:
    id: str
    archetype: str
    run_id: str | None = None
    status: str = "on_task"


def new_cell_id(archetype: str) -> str:
    return f"{archetype}-{uuid.uuid4().hex[:8]}"


def find_archetype(cfg: SomaConfig, name: str, project_dir: Path | None = None):
    """Resolve one archetype by name, or fail naming what exists."""
    from soma.archetypes import load_archetypes

    definitions = {d.name: d for d in load_archetypes(cfg, project_dir)}
    if name not in definitions:
        have = ", ".join(sorted(definitions)) or "none found"
        raise ValueError(
            f"no archetype named '{name}' (available: {have}) — "
            "see docs/archetypes.md and: soma archetypes list"
        )
    return definitions[name]


def layered_suffix(definition) -> str:
    """B3 stable prefix: archetype core, then the mode overlay. Nothing else."""
    return f"{definition.system_prompt}\n\n{TASK_MODE_OVERLAY}"


def _resolve_skills(definition, work_dir: Path | None) -> list:
    """Names from the archetype's `skills:` list -> Skill objects, pre-flight."""
    if not definition.skills:
        return []
    from soma.skills import load_skills

    available = load_skills(work_dir)
    missing = [n for n in definition.skills if n not in available]
    if missing:
        have = ", ".join(sorted(available)) or "none found"
        raise ValueError(
            f"archetype '{definition.name}': unknown skills {missing} "
            f"(available: {have}) — see: soma skills list"
        )
    return [available[n] for n in definition.skills]


def mint_agent(cfg: SomaConfig, definition, condense_at: int | None = None,
               work_dir: Path | None = None):
    """Archetype definition -> SDK Agent, per the wiring above.

    The layers are composed into the STATIC system prompt, not the
    SDK's dynamic-context block: EXP-003 showed the local tier obeys
    inline text and ignores the second content block. This also makes
    the prompt byte-identical for every cell of an archetype — the B3
    stable prefix, and exactly what prefix caching wants.
    """
    from openhands.sdk import Agent, LLMProfileStore, Tool
    from openhands.tools import register_default_tools

    from soma.engine import build_condenser

    register_default_tools(enable_browser=False)
    if definition.model in ("", "inherit"):
        raise ValueError(
            f"archetype '{definition.name}' has no tier (model: inherit) — "
            "soma cells always name their seat; set model: <tier>"
        )
    store = LLMProfileStore(cfg.profile_store_path)
    try:
        llm = store.load(definition.model.removesuffix(".json"))
    except Exception as exc:  # same actionable hint as validation
        raise ValueError(
            f"archetype '{definition.name}': tier '{definition.model}' has no "
            f"profile at {cfg.profile_store_path} ({exc}) — run: soma init"
        ) from exc
    llm = llm.model_copy(update={
        "usage_id": f"agent:{definition.name}",
        "timeout": ENGINE_LLM_TIMEOUT,
        "num_retries": ENGINE_LLM_RETRIES,
    })
    tools = [Tool(name=n) for n in definition.tools]
    skills = _resolve_skills(definition, work_dir)
    base = Agent(llm=llm, tools=tools).static_system_message
    agent_kwargs: dict = {}
    if skills:
        from openhands.sdk import AgentContext

        agent_kwargs["agent_context"] = AgentContext(skills=skills)
    return Agent(
        llm=llm,
        tools=tools,
        condenser=build_condenser(cfg, condense_at),
        system_prompt=f"{base}\n\n{layered_suffix(definition)}",
        **agent_kwargs,
    )
