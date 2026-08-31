"""Proto-cell engine — one task, one Conversation, one run bundle (PR-02).

This is the engine the Cell Protocol (PR-04) will wrap. No protocol
yet: hand it a task string and it births one SDK Conversation on a
workspace, lets it run to a terminal status, and reports what
happened. Layer doctrine (ADR-010): the engine knows nothing about
teams, boards, or memory.

Wiring that matters:
- agent LLM = the tier profile you name (fit-first; default worker)
- condenser = LLMSummarizingCondenser on the LOCAL tier, rebadged
  usage_id "condenser" so the ledger reports it apart from the agent
- persistence_dir = runs/<run_id>/ — restore data, reconstruct
  definitions: the event log survives any crash
- typed LLM exceptions map to short, actionable verdicts
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from soma.config import SomaConfig

DEFAULT_MAX_ITERATIONS = 100
# SDK defaults are timeout=300s x 5 retries: a hung provider looks frozen for
# ~25 minutes. A proto-cell should fail typed and fast instead (error:timeout).
ENGINE_LLM_TIMEOUT = 120
ENGINE_LLM_RETRIES = 2


@dataclass
class RunResult:
    run_id: str
    status: str  # finished / stuck / error:<kind> / interrupted / ...
    persistence_dir: Path
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "finished"


def new_run_id() -> str:
    """Sortable, human-scannable: 20260830-163055-a1b2c3."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


def _load_tier(cfg: SomaConfig, name: str):
    from openhands.sdk import LLMProfileStore

    store = LLMProfileStore(cfg.profile_store_path)
    try:
        return store.load(name)
    except Exception as exc:  # any load failure gets the same actionable hint
        raise ValueError(
            f"tier '{name}' has no loadable profile at {cfg.profile_store_path} "
            f"({exc}) — declare it in soma.toml and run: soma init"
        ) from exc


def build_agent(cfg: SomaConfig, tier: str = "worker", condense_at: int | None = None):
    """Agent on the named tier; condenser always on the local tier."""
    from openhands.sdk import Agent, LLMSummarizingCondenser, Tool
    from openhands.tools import register_default_tools

    register_default_tools(enable_browser=False)
    clamp = {"timeout": ENGINE_LLM_TIMEOUT, "num_retries": ENGINE_LLM_RETRIES}
    agent_llm = _load_tier(cfg, tier).model_copy(update=clamp)
    condenser_llm = _load_tier(cfg, "local").model_copy(
        update={"usage_id": "condenser", **clamp}
    )
    condenser_args: dict[str, Any] = {"llm": condenser_llm}
    if condense_at is not None:
        # SDK invariant: max_size // 2 > keep_first + 1 (keep_first defaults to 2).
        if condense_at < 8:
            raise ValueError("--condense-at must be at least 8 (SDK condenser minimum)")
        condenser_args["max_size"] = condense_at
    return Agent(
        llm=agent_llm,
        tools=[Tool(name="terminal"), Tool(name="file_editor")],
        condenser=LLMSummarizingCondenser(**condenser_args),
    )


def _make_conversation(agent, workspace: Path, persistence_dir: Path,
                       max_iterations: int, visualize: bool):
    from openhands.sdk import Conversation

    return Conversation(
        agent,
        workspace=str(workspace),
        persistence_dir=str(persistence_dir),
        max_iteration_per_run=max_iterations,
        visualizer=None if not visualize else _default_visualizer(),
        delete_on_close=False,
    )


def _default_visualizer():
    from openhands.sdk.conversation.visualizer.default import (
        DefaultConversationVisualizer,
    )

    return DefaultConversationVisualizer


def _llm_error_hints():
    from openhands.sdk.llm.exceptions import (
        LLMAuthenticationError,
        LLMContextWindowExceedError,
        LLMError,
        LLMNoResponseError,
        LLMRateLimitError,
        LLMServiceUnavailableError,
        LLMTimeoutError,
    )

    # Order matters: specific first, LLMError last as the net.
    return (
        (LLMAuthenticationError, "auth",
         "credentials rejected — is OPENROUTER_API_KEY exported? then: soma init --force"),
        (LLMRateLimitError, "rate-limit",
         "provider rate limit — wait and retry, or repoint the tier in soma.toml"),
        (LLMTimeoutError, "timeout", "provider timed out — transient, retry"),
        (LLMServiceUnavailableError, "unavailable",
         "provider unavailable — transient, retry or repoint the tier"),
        (LLMContextWindowExceedError, "context-window",
         "context overflow despite condensation — lower --condense-at"),
        (LLMNoResponseError, "no-response", "provider returned nothing — retry"),
        (LLMError, "llm-error", "unclassified LLM failure — see message"),
    )


def run_task(
    task: str,
    cfg: SomaConfig,
    tier: str = "worker",
    workspace: Path | None = None,
    run_id: str | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    condense_at: int | None = None,
    visualize: bool = True,
) -> RunResult:
    """Run one task to a terminal status. The run bundle always survives."""
    run_id = run_id or new_run_id()
    persistence_dir = cfg.runs_path / run_id
    persistence_dir.mkdir(parents=True, exist_ok=True)
    agent = build_agent(cfg, tier=tier, condense_at=condense_at)
    conversation = _make_conversation(
        agent, workspace or Path.cwd(), persistence_dir, max_iterations, visualize
    )
    try:
        conversation.send_message(task)
        conversation.run()
    except KeyboardInterrupt:
        return RunResult(run_id, "interrupted",
                         persistence_dir, "stopped by user; event log kept")
    except Exception as exc:
        for exc_type, kind, hint in _llm_error_hints():
            if isinstance(exc, exc_type):
                return RunResult(run_id, f"error:{kind}", persistence_dir, f"{hint} ({exc})")
        raise
    status = conversation.state.execution_status.value
    return RunResult(run_id, status, persistence_dir)
