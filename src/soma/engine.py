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


def clamp_llm(llm):
    """Fill missing safety limits on an LLM.

    Profiles written by `soma init` already carry per-tier limits from
    soma.toml (max_output_tokens / timeout / retries) and those win.
    This only catches hand-added profiles: an uncapped max_tokens asks
    the provider to reserve the model's full output limit (384K on some)
    against your balance — OpenRouter answers 402.
    """
    from soma.config import CLOUD_LIMITS

    if llm.max_output_tokens is None:
        return llm.model_copy(update={"max_output_tokens": CLOUD_LIMITS["max_output_tokens"]})
    return llm


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


def build_condenser(cfg: SomaConfig, condense_at: int | None = None):
    """The standard cell condenser: local tier, own ledger name, clamped."""
    from openhands.sdk import LLMSummarizingCondenser

    condenser_llm = clamp_llm(_load_tier(cfg, "local")).model_copy(
        update={"usage_id": "condenser"}
    )
    condenser_args: dict[str, Any] = {"llm": condenser_llm}
    if condense_at is not None:
        # SDK invariant: max_size // 2 > keep_first + 1 (keep_first defaults to 2).
        if condense_at < 8:
            raise ValueError("--condense-at must be at least 8 (SDK condenser minimum)")
        condenser_args["max_size"] = condense_at
    return LLMSummarizingCondenser(**condenser_args)


def build_agent(cfg: SomaConfig, tier: str = "worker", condense_at: int | None = None,
                extra_tools: list | None = None):
    """The identity-less proto-cell agent on the named tier."""
    from openhands.sdk import Agent, Tool
    from openhands.tools import register_default_tools

    register_default_tools(enable_browser=False)
    agent_llm = clamp_llm(_load_tier(cfg, tier))
    return Agent(
        llm=agent_llm,
        tools=[Tool(name="terminal"), Tool(name="file_editor"), *(extra_tools or [])],
        condenser=build_condenser(cfg, condense_at),
    )


def _make_conversation(agent, workspace: Path, persistence_dir: Path,
                       max_iterations: int, visualize: bool,
                       conversation_id=None):
    import uuid as uuid_mod

    from openhands.sdk import Conversation

    from soma.hooks import soma_hook_config  # Beads discipline as SDK hooks (PR-09)

    # Mint the id here so the hooks can be keyed by the conversation dir
    # (<bundle>/<id.hex>) — the same key the cell's bd tools use for its board.
    conversation_id = conversation_id or uuid_mod.uuid4()
    return Conversation(
        agent,
        workspace=str(workspace),
        persistence_dir=str(persistence_dir),
        conversation_id=conversation_id,
        max_iteration_per_run=max_iterations,
        visualizer=None if not visualize else _default_visualizer(),
        delete_on_close=False,
        hook_config=soma_hook_config(Path(persistence_dir) / conversation_id.hex),
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


_STATUS_HINTS = {
    401: ("auth", "credentials rejected — check the key in the tier profile (soma init --force)"),
    403: ("auth", "provider refused the key — check the key in the tier profile"),
    402: ("credits", ("provider balance too low for this request — add credits, "
                      "or lower ENGINE_MAX_OUTPUT_TOKENS")),
    408: ("timeout", "provider timed out — transient, retry"),
    429: ("rate-limit", "provider rate limit — wait and retry, or repoint the tier"),
}


def _short(exc: BaseException, limit: int = 240) -> str:
    text = " ".join(str(exc).split())
    return text if len(text) <= limit else text[:limit] + "…"


def classify_llm_error(exc: BaseException) -> tuple[str, str] | None:
    """Map an exception — walking its cause chain — to (kind, hint), or None.

    The SDK wraps provider failures in ConversationRunError and litellm
    errors carry a status_code; unwrapping keeps verdicts typed instead
    of surfacing as stack traces.
    """
    chain: list[BaseException] = []
    cur: BaseException | None = exc
    while cur is not None and cur not in chain:
        chain.append(cur)
        cur = cur.__cause__ or cur.__context__
    hints = _llm_error_hints()
    for e in chain:
        for exc_type, kind, hint in hints:
            if isinstance(e, exc_type):
                return kind, hint
    for e in chain:
        code = getattr(e, "status_code", None)
        if code in _STATUS_HINTS:
            return _STATUS_HINTS[code]
        if isinstance(code, int) and code >= 500:
            return "unavailable", "provider unavailable — transient, retry or repoint the tier"
        name = type(e).__name__
        text = str(e)
        if "Timeout" in name:
            return _STATUS_HINTS[408]
        if "RateLimit" in name:
            return _STATUS_HINTS[429]
        if "Authentication" in name:
            return _STATUS_HINTS[401]
        if "requires more credits" in text or '"code":402' in text:
            return _STATUS_HINTS[402]
    return None


def run_task(
    task: str,
    cfg: SomaConfig,
    tier: str = "worker",
    archetype: str | None = None,
    workspace: Path | None = None,
    run_id: str | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    condense_at: int | None = None,
    visualize: bool = True,
) -> RunResult:
    """Run one task to a terminal status. The run bundle always survives.

    With `archetype`, the agent is minted from that role file (its
    `model:` tier wins over the `tier` argument; ledger meters it as
    `agent:<name>`). Without it, the identity-less proto-cell runs.
    """
    from soma.telemetry import record_run, utcnow_iso

    run_id = run_id or new_run_id()
    persistence_dir = cfg.runs_path / run_id
    persistence_dir.mkdir(parents=True, exist_ok=True)
    workspace = workspace or Path.cwd()
    started_at = utcnow_iso()

    # Kind-2 log: the run's WAL. B1 — the briefing is the first entry of the
    # cell's task log, written by the harness before the cell takes a breath.
    from soma.cells import new_cell_id
    from soma.wal import open_run_wal, wal_tool_specs, write_briefing

    cell_id = new_cell_id(archetype or "proto")
    wal = open_run_wal(persistence_dir)
    write_briefing(wal, cell_id, task)
    extra_tools = wal_tool_specs(wal.path, cell_id)  # membrane tools, scoped to this cell
    wal.close()

    if archetype is not None:
        from soma.cells import find_archetype, mint_agent

        definition = find_archetype(cfg, archetype, project_dir=workspace)
        agent = mint_agent(cfg, definition, condense_at=condense_at,
                           work_dir=workspace, extra_tools=extra_tools)
        tier = definition.model  # the ledger records the seat actually used
    else:
        agent = build_agent(cfg, tier=tier, condense_at=condense_at,
                            extra_tools=extra_tools)
    conversation = _make_conversation(
        agent, workspace, persistence_dir, max_iterations, visualize
    )

    def _record(status: str) -> None:
        # harness-side, after the fact, best-effort (layer doctrine: the
        # cell never knows the ledger exists; a ledger hiccup never fails a run)
        record_run(cfg, run_id, task, tier, str(workspace), status,
                   persistence_dir, started_at)

    try:
        conversation.send_message(task)
        conversation.run()
    except KeyboardInterrupt:
        _record("interrupted")
        return RunResult(run_id, "interrupted",
                         persistence_dir, "stopped by user; event log kept")
    except Exception as exc:
        classified = classify_llm_error(exc)
        if classified:
            kind, hint = classified
            _record(f"error:{kind}")
            return RunResult(run_id, f"error:{kind}", persistence_dir,
                             f"{hint} ({_short(exc)})")
        _record("error:crash")
        raise
    status = conversation.state.execution_status.value
    _record(status)
    return RunResult(run_id, status, persistence_dir)


def resume_run(
    run_id: str,
    cfg: SomaConfig,
    tier: str | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    condense_at: int | None = None,
    visualize: bool = True,
) -> RunResult:
    """Continue a dead-but-unfinished run (Cell Protocol R1/R2).

    Restore data, reconstruct definitions: the event log and workspace
    come from the bundle, the conversation_id from base_state.json, and
    the Agent is rebuilt from CURRENT config (tier from the ledger's
    memory of the run unless overridden). The SDK sees the existing
    SystemPromptEvent and continues — it never re-inits (R2).
    """
    import uuid as uuid_mod

    from soma.telemetry import harvest_bundle, record_run, run_meta, utcnow_iso

    persistence_dir = cfg.runs_path / run_id
    state = harvest_bundle(persistence_dir)
    if state is None:
        raise ValueError(
            f"no bundle for run '{run_id}' under {cfg.runs_path} — nothing to resume"
        )
    meta = run_meta(cfg, run_id) or {}
    tier = tier or meta.get("tier") or "worker"
    conversation_id = uuid_mod.UUID(state["id"])
    workspace = Path(state["workspace"]["working_dir"])
    started_at = meta.get("started_at") or utcnow_iso()
    task = meta.get("task") or "(resumed; original task in event log)"
    # re-mount the WAL membrane tools if this run has a WAL (post-PR-10 bundles)
    from soma.wal import WAL_FILENAME, WalStore, wal_tool_specs

    extra_tools: list = []
    wal_path = persistence_dir / WAL_FILENAME
    if wal_path.is_file():
        store = WalStore(wal_path)
        cell_ids = [c.removeprefix("cell:") for c in store.channels() if c.startswith("cell:")]
        store.close()
        if cell_ids:
            extra_tools = wal_tool_specs(wal_path, cell_ids[0])
    agent = build_agent(cfg, tier=tier, condense_at=condense_at, extra_tools=extra_tools)
    conversation = _make_conversation(
        agent, workspace, persistence_dir, max_iterations, visualize,
        conversation_id=conversation_id,
    )

    def _record(status: str) -> None:
        record_run(cfg, run_id, task, tier, str(workspace), status,
                   persistence_dir, started_at)

    try:
        conversation.run()
    except KeyboardInterrupt:
        _record("interrupted")
        return RunResult(run_id, "interrupted",
                         persistence_dir, "stopped by user; event log kept")
    except Exception as exc:
        classified = classify_llm_error(exc)
        if classified:
            kind, hint = classified
            _record(f"error:{kind}")
            return RunResult(run_id, f"error:{kind}", persistence_dir,
                             f"{hint} ({_short(exc)})")
        _record("error:crash")
        raise
    status = conversation.state.execution_status.value
    _record(status)
    return RunResult(run_id, status, persistence_dir)
