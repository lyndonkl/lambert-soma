# Lambert-Soma — Implementation Plan (post-L2)

*Status: living · created 2026-08-29 after the OpenHands SDK deep-dive (L2)*
*Companion to [PLAN.md](../PLAN.md). PLAN.md holds the what and the phases; this file holds the how — every soma subsystem mapped to the exact SDK mechanism chosen, with the guide that documents it. Decisions behind these choices: ADR-005 through ADR-008.*

All guide paths below are relative to `https://docs.openhands.dev`.

## 1. Subsystem → SDK mechanism map

| Soma subsystem | SDK mechanism | Guide | What we still write |
|---|---|---|---|
| Cell task engine | `Agent` + `Conversation(workspace, persistence_dir, conversation_id)` — one per task activity | `/sdk/guides/hello-world`, `/sdk/guides/convo-persistence` | the Cell wrapper: identity, status, activity lifecycle |
| Archetypes (ADR-006) | file-based agents `.agents/agents/*.md`, `register_file_agents()`; extensions via `metadata: soma_*` | `/sdk/guides/agent-file-based` | conventions + validation pass; port tooling |
| Tiers | `LLMProfileStore` profiles `local`/`worker`/`lead`; archetypes bind via `model: <profile>`; `FallbackStrategy` for cloud resilience; per-instance `usage_id` | `/sdk/guides/llm-profile-store`, `/sdk/guides/llm-fallback` | profile bootstrap in soma init; the fit-first assignment policy |
| Local tier | `LLM(base_url="http://localhost:8000/v1", input_cost_per_token=0, output_cost_per_token=0)` | `/sdk/arch/llm` | done — `soma local up` (P1, ADR-005) |
| In-team delegation | `TaskToolSet` + `register_agent`; resume via `task_id`; parallel fan-out via `tool_concurrency_limit` (experimental — default 1, leads get 2–4) | `/sdk/guides/task-tool-set`, `/sdk/guides/parallel-tool-execution` | org-compiler wiring; S4 verification |
| Cross-team / peer comms | none — entirely soma: SQLite WAL (scope column, cursors) + `wal_publish`/`wal_read` as custom tools (shared executor holds the db handle) | `/sdk/guides/custom-tools` (patterns only) | the whole fabric (PLAN §5.2) |
| Inbox delivery | primary candidate: `conversation.send_message()` **while running** — documented as safe mid-execution; fallback: drive `step()` ourselves | `/sdk/guides/convo-send-message-while-running` | the WAL watcher; spike S8 decides |
| Planner → OrgPlan | agent whose finish tool carries `response_schema=OrgPlan` — typed, validated on receipt, `parse_last_response()` survives persistence | `/sdk/guides/structured-output` | OrgPlan schema, templates, retry-on-invalid |
| Dialogues | harness-composed turns via direct `llm.completion()`; RESOLVED move as a small `response_schema` tool if we give dialogue turns one tool | `/sdk/guides/structured-output` | dialogue loop, overlays, ToM block (PLAN §5.2 lifecycle) |
| Discipline & gates | hooks: `UserPromptSubmit` injects context (beads digest), `PreToolUse` blocks, `Stop` refuses premature finish; **exit code 2 blocks, 1 does not** | `/sdk/guides/hooks` | the policies themselves |
| Team completion | `judge_goal(judge_llm, objective, events)` per team `done_when`; `GoalController` for the loop shape; `Critic` as optional per-run gate | `/sdk/guides/goal`, `/sdk/guides/critic` | orchestrator composition across teams |
| Sentinels | stuck detector (default on) + our semantic checker as an event callback hitting LOCAL; `Ensemble(PolicyRail, Pattern)` deterministic analyzers; `ConfirmRisky` interactive / `NeverConfirm` in Docker; `max_iteration_per_run` hard cap; `conversation.pause()` | `/sdk/guides/agent-stuck-detector`, `/sdk/guides/security` | semantic tier, escalation ladder, apoptosis post-mortems |
| ToM (ADR-007) | Tom tools substrate: `TomConsultTool`, `SleeptimeComputeTool`, user models in `~/.openhands/user_models/` | `/sdk/guides/tom-agent` | style ensemble, router/composer, agent-to-agent ToM; spike S9 first |
| Memory (ADR-008) | `AgentContext(load_memory=True)` for project/user facts (orchestrator is sole writer); soma archetype store separate (ADR-002 pending L9); copy the `<UNTRUSTED_CONTENT>` wrapper | `/sdk/guides/persistent-memory` | archetype pipeline: reflection → episodes → consolidation → gated skill promotion |
| Skills port | AgentSkills `SKILL.md` (progressive disclosure) — **never** legacy `trigger=None` (full text in every turn); plugins bundle skills+hooks+agents+MCP, Claude Code compatible | `/sdk/guides/skill`, `/sdk/guides/plugins` | audit gate; port tooling for the 265-skill library |
| Telemetry | `conversation.conversation_stats` (per-`usage_id` cost/tokens/cache read+write); persistence dirs as replay bundles; `fork()` for A/B; optional OTEL via env (`/sdk/guides/observability`) | `/sdk/guides/metrics`, `/sdk/guides/convo-fork` | ledger aggregation, config hashing, `soma report` |
| Interactive main loop | `send_message` while running, `pause()`/`run()`, `ask_agent()` sidebar queries, custom `ConversationVisualizerBase` | respective convo guides | `soma chat` UX; `soma top` |
| Isolation | `LocalWorkspace` ↔ `DockerWorkspace(server_image=…)` swap; `extra_ports` for VSCode/VNC later | `/sdk/guides/agent-server/docker-sandbox` | run-mode policy (interactive=local, unattended=docker) |
| Secrets | `conversation.update_secrets()` + SecretSource; masked in output | `/sdk/guides/secrets` | which keys each archetype may see |

## 2. Phase deltas (what changed in P2–P9)

**P2 — spine.** Bootstrap the three LLM profiles (`local` with `base_url` + zero costs, `worker`, `lead`) in the profile store. One cell = file-based default agent + Conversation with `persistence_dir=runs/<run_id>/…`. Condenser LLM = `local` profile via `model_copy(update={"usage_id": "condenser"})`. Telemetry v0 reads `conversation_stats.usage_to_metrics` into our ledger — we aggregate, never meter. Typed exception handling per `/sdk/guides/llm-error-handling`.

**P3 — differentiation.** `register_file_agents(project_dir)` replaces our loader. Ten archetypes as `.agents/agents/*.md` with `model: <profile>`. Skills ported in AgentSkills format only. Audit gate before anything gets shell tools (skills can execute `` !`cmd` `` at render — they are code).

**P4 — teams.** Lead cells get `Tool(name=TaskToolSet.name)` with registered member archetypes; `tool_concurrency_limit=2–4` on leads (experimental — watch it). Beads wrapper tools plus discipline hooks: `UserPromptSubmit` injects the ready-beads digest, `Stop` hook refuses finish until `done_when` artifacts exist. Bench v0 measures the delegation-overhead multiplier.

**P5 — WAL.** Unchanged in design (it's the part the SDK doesn't have). Implementation notes: custom tools share one executor holding the SQLite handle; inbox delivery via S8's winner.

**P6 — organizations.** Planner emits OrgPlan through `response_schema`. Org compiler builds cells (Conversations), delegation trees (TaskToolSet registrations), and WAL channels from the plan. Per-team completion = `judge_goal` with a judge LLM (LOCAL first; escalate judge to LEAD if precision demands). `OpenHandsAgentSettings` serialization feeds our config-hash for the run ledger.

**P7 — sentinels.** Rules tier confirmed default-on. Semantic tier = event callback → LOCAL endpoint (not a prompt-hook — see S10). Deterministic layer = `EnsembleSecurityAnalyzer([PolicyRail, Pattern])`. Escalation uses `pause()`, `max_iteration_per_run`, and kill-with-post-mortem. Shadow mode stays ours: log verdicts without authority for a week.

**P8 — ToM.** Starts with S9 (inspect Tom storage). Then extend their user model; style archetypes are toolless file-based agents; composer runs per turn; A/B via `fork()` on real conversations (same history, ToM on/off).

**P9 — memory.** Scope shrunk per ADR-008: archetype pipeline only. Reflection mines ALL of a cell's activity persistence dirs. `load_memory=True` on the orchestrator's main loop only (single-writer rule).

## 3. Kill-list updates (new spikes)

| # | Assumption | Test | If false |
|---|---|---|---|
| S4 (reworded) | TaskToolSet handles our lead→member topology: registration, fan-in, resume by task_id, parallel calls | verification spike, not exploration | compiler-managed Conversations per member |
| S8 (new) | `send_message()` while running is a safe, ordered inbox-delivery channel for WAL digests | two-cell handoff using only mid-run sends | harness drives `step()` directly and injects between steps |
| S9 (new) | Tom tools' stored user model is rich enough to extend (schema, cadence, cost of sleeptime compute) | run the tools, read `~/.openhands/user_models/*/user_model.json` | ADR-007 falls back to independent build with theirs as reference |
| S10 (new) | Semantic gates can run on LOCAL regardless of a cell's tier. Caveat found in docs: **prompt-hooks copy the conversation's current LLM** — on a LEAD cell they'd bill LEAD | route gates as command-hooks curling `localhost:8000`, or event callbacks; measure | accept prompt-hooks only on LOCAL-tier cells; everything else uses callbacks |

## 4. Traps recorded from the guides

- Hook exit code 1 does NOT block — only 2 does. A "policy" hook exiting 1 is a silent no-op.
- Legacy always-on skills inject full content into every turn. AgentSkills format or token bomb.
- `execute_tool()` bypasses security analyzers and confirmation policy.
- Parallel tool execution is experimental; default is sequential. Shared-state tools are not safe under it.
- MEMORY.md is agent-maintained and untrusted-by-design; a cloned repo can ship one (injection vector).
- OAuth MCP servers need a browser — unusable in headless org runs.
- `openhands-sdk` and `openhands-tools` must be installed pinned together in one command.
