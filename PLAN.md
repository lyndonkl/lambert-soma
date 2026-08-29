# Lambert-Soma — End-to-End Plan

**Status:** living document · started 2026-08-28 · Phase P0 complete
**Companion:** [README.md](README.md) for the what and why. This file is the how.
**Reference hardware:** Apple M3 Max, 96 GB unified memory. Cost target: replace a $200/mo subscription with < $100/mo.

---

## 0. How this document works

The work runs on four interleaved tracks. No track finishes before the others start; they braid.

| Track | What it produces | Lives in |
|---|---|---|
| **Learn** | Mental models of each component, built by pasting docs into sessions | `docs/mental-models/` |
| **Build** | The harness itself, phase by phase | `src/soma/`, `spikes/` |
| **Research** | The novel subsystems: org planning, WAL comms, theory of mind, archetype memory | design sections below, then code |
| **Measure** | Telemetry, experiments, benchmarks — proof the thing works and where it's weak | `docs/experiments/`, `bench/`, `telemetry/` |

### The learning-session protocol

Each Learn unit runs the same way:

1. Open a session. Name the unit (for example "L4: Condenser"). Paste the docs listed for it.
2. Claude maps the component onto Lambert-Soma: capabilities we leverage, capabilities we skip, gotchas, and the exact wiring points into our modules.
3. Pressure-test the model. Claude asks 3–5 Socratic questions; you ask yours. Stop when it clicks, not when the doc ends.
4. Co-write `docs/mental-models/NN-<component>.md` from [the template](docs/mental-models/TEMPLATE.md).
5. Update this plan's checkboxes. If the design shifted, write an ADR in `docs/decisions/`.
6. Run the unit's paired spike (tiny throwaway code in `spikes/`). Commit as `learn(L4): condenser mental model + spike`.

### Conventions

- **Mental models** → `docs/mental-models/NN-name.md` (numbered in curriculum order)
- **Decisions** → `docs/decisions/ADR-NNN-title.md` (context, options, choice, consequences)
- **Experiments** → `docs/experiments/EXP-NNN-title.md` (hypothesis, variable, metric, result, decision)
- **Spikes** → `spikes/` — disposable, never imported by `src/`
- **Real code** → `src/soma/`, tested, typed, ruff-clean
- Commits: `learn(Lx):`, `build(Px):`, `exp(EXP-NNN):`, `adr(NNN):`, `docs:`

---

## 1. Goals, non-goals, success criteria

### Goals

- **G1 — Orchestrator.** One main loop that takes a goal and decides: solo, or organization.
- **G2 — Organizations.** Single or multiple teams, flat or hierarchical, collaborating. The user can supply a team design. If they don't, a planner subagent generates one — including custom, inline-defined subagent archetypes — validated against a schema before anything spawns.
- **G3 — Communication fabric.** Private per-agent event logs plus one shared write-ahead log of typed events. Beads carries work state (ready/claimed/blocked/discovered). Agents coordinate without sharing a context window.
- **G4 — Theory-of-mind conversation.** The conversational agent models its interlocutor explicitly and delegates within itself to cognitive-style subagents (analysis, questioning, explaining, critique, synthesis), composing their outputs into replies.
- **G5 — Archetype memory.** Generic agent *types* — not instances — grow episodic, semantic (long-term), procedural, and temporal/periodic memory across runs.
- **G6 — Hybrid routing.** LOCAL (M3 Max) / WORKER (cheap cloud) / LEAD (frontier) tiers, bound per agent and per subsystem, with per-`usage_id` cost attribution.
- **G7 — Self-measurement.** The harness instruments itself: run ledger, replayable logs, shadow-mode rollouts, benchmark suite. We learn where it's weak from data, not vibes.
- **G8 — Safety.** Sandboxed unattended runs, sentinels with kill authority, budget circuit breakers, audited skills.

### Non-goals (v0.x)

- No web UI. CLI (and later a TUI) only.
- No Letta — it wants to own the loop; OpenHands owns our loop. Mem0 or a custom store instead.
- No constrained decoding / structured-generation stack. Validate-and-retry with a cheap local fix-up call.
- No fine-tuning, ever, in this repo. The Weismann barrier: all learning is somatic (memory, skills, prompts).
- No multi-machine distribution. One Mac plus cloud APIs.
- No cross-platform local tier. v0 is Apple Silicon only, enforced by a packaging marker (`vllm-mlx ; sys_platform == 'darwin' and platform_machine == 'arm64'`), never by scattered platform checks. A `LocalProvider` interface (detect / install / download / serve / verify) keeps the methodology generic: other backends (CUDA vLLM, llama.cpp) become new providers later. Off-Mac, the harness runs cloud-only — LOCAL work falls through to WORKER with a warning. See ADR-005.
- Not a general framework for other people's stacks yet. Build for ours; generalize when it works.

### Success criteria for v0.1 ("it replaced the subscription")

1. **Daily driver.** The orchestrator handles real solo tasks end to end at quality parity with the current workflow.
2. **Org run.** One org template executes a two-team hierarchical job unattended, in Docker, to its `done_when`, with zero human interventions.
3. **Coordination.** Two agents complete a handoff purely via the shared WAL + Beads — no shared prompt, no shared context window.
4. **Memory lift.** For one archetype and one task class repeated 5+ times, tokens-to-done or interventions trend measurably down.
5. **Cost.** Two consecutive weeks under $25/week at normal usage, verified from the `usage_id` ledger.
6. **ToM.** Blind A/B on 20 real conversation turns: ToM-composed replies preferred ≥ 60%.
7. **Instrumented.** Every subsystem above ships with at least one EXP one-pager showing its measured effect.

---

## 2. Target architecture

### 2.1 Process topology

Three OS processes, same as the reference design:

```
1. vllm-mlx serve …            # local model server, localhost:8000 (OpenAI + Anthropic APIs)
2. bd …                        # Beads CLI, invoked per-command, no daemon
3. python -m soma …            # the harness: orchestrator, teams, sentinels, telemetry
```

Everything else — routing, condenser, memory, WAL, ToM — is a library inside process 3.

### 2.2 Module map

| Module | Responsibility |
|---|---|
| `soma.orchestrator` | Main loop; solo⇄org decision; run lifecycle |
| `soma.org` | OrgPlan schema; planner subagent; org compiler → team runtimes; templates library |
| `soma.comms` | Shared WAL (SQLite), event types, cursors, inbox injection; Beads wrapper tools |
| `soma.tom` | Interlocutor model; cognitive-style registry; turn pipeline; composer |
| `soma.memory` | Archetype memory: episodic store, consolidation ("sleep"), procedural promotion, retrieval |
| `soma.routing` | Tier definitions; agent factory; `usage_id` accounting; router policies |
| `soma.local` | Local substrate providers (detect/install/download/serve/verify); v0: vllm-mlx on Apple Silicon (ADR-005); `soma local up`, `soma doctor --local` |
| `soma.sentinels` | Rule + semantic loop detection; budget breakers; escalation ladder; apoptosis |
| `soma.telemetry` | Run ledger; structured logs; replay bundles; canaries; `soma report` |
| `soma.archetypes` | Agent type definitions (markdown + YAML frontmatter), loader, validation |
| `soma.cli` | `soma chat`, `soma run`, `soma org run`, `soma bench`, `soma report`, `soma top` |

### 2.3 Data at rest

| Data | Where | Retention |
|---|---|---|
| Per-agent event logs (OpenHands) | `runs/<run_id>/agents/<agent>/` | 30 days full, then condensed archive |
| Shared WAL | `runs/<run_id>/wal.sqlite3` | kept with run bundle |
| Beads issues | target project's `.beads/` (JSONL committed) | forever, it's git |
| Archetype memory | `~/.soma/memory/` (per-archetype namespaces) | decay policy, see §5.4 |
| Telemetry ledger | `~/.soma/telemetry.db` | forever (it's small rows, not logs) |
| Run bundles (replayable) | `runs/<run_id>/` | 30 days, pinned if referenced by an EXP |

---

## 3. Learn track — the curriculum

Order is dependency-driven: each unit unlocks the build phase next to it. Paste the listed docs; the mental-model doc must be able to answer the listed questions from memory.

| # | Component | Docs to paste | Your mental model must answer | Paired spike |
|---|---|---|---|---|
| **L1** | vllm-mlx + MLX models | repo README, installation, server docs | How do continuous batching, prefix caching, paged KV interact with 10 concurrent agents? What breaks tool-call *formatting* on quantized models? How does tok/s degrade with context length? | **S1/S7**: serve Qwen3-Coder-30B-A3B-4bit; 10-turn tool-call soak; measure tok/s at 1K/16K/64K ctx |
| **L2** | OpenHands SDK core | `/sdk/arch/sdk`, llms.txt index | What exactly is an event? What is immutable vs mutable (`ConversationState` only)? Where does the loop live? V0 vs V1 — how do we spot wrong docs? | hello-agent; read the raw event log it produced |
| **L3** | Tools & Workspaces (+ security analyzer) | tools guide, workspace docs | How are actions serialized (the semaphore)? What differs between Local and Docker workspaces? Where does the security analyzer intercept? | same agent, both workspaces, diff behavior |
| **L4** | Condenser | condenser guide + arch page | What triggers condensation? What survives (`keep_first`)? Why is it a *view* over an intact log? What does it do to prompt caches? | force a condensation on LOCAL; inspect the CondensationEvent |
| **L5** | Skills & file-based agents | skills guide, agent-file-based guide | Always-on vs triggered skills? Load order and precedence? How do `AGENTS.md`/`CLAUDE.md` interact? What frontmatter is ours (e.g. `tier:`)? | port 3 skills + 2 agents from the library |
| **L6** | LLM class & routing | LLM docs; `model_copy`/`usage_id`/Metrics; router-as-LLM | Four binding levels (global / per-agent / per-subsystem / router)? How do Metrics roll up? Why copy-not-mutate? | **S2**: mixed local+OpenRouter run; verify independent Metrics per `usage_id` |
| **L7** | Delegation | deepwiki sub-agent delegation internals | What context does a child inherit? How do results return to the parent? What concurrency is allowed? Can we address a *specific* delegate later? | **S4**: lead + 2 children fan-out/fan-in |
| **L8** | Beads | beads docs, MOLECULES.md | What enforces discipline (hooks vs prompts)? How do we namespace teams on one board? What are molecules and when do we want them? | **S6**: two agents share a board through wrapper tools |
| **L9** | Mem0 (vs custom store) | mem0 docs, graph variant | What does extraction actually store? Can namespace = archetype? What's the latency and where does it run (LOCAL)? What are its failure modes? | seed one archetype with 5 synthetic episodes; measure recall quality |
| **L10** | MCP | MCP guide | When is a tool an MCP server vs a native tool? What's the security posture for third-party servers? | wire one MCP server (web search) to one agent |

Mental-model docs are numbered `01-vllm-mlx.md` … `10-mcp.md`. Add units freely (Langfuse, DuckDB) as needed — number them in arrival order.

---

## 4. Build track — phases and exit criteria

Every phase's exit criteria include its telemetry. If we didn't measure it, we didn't build it.

### P0 — Repo bootstrap ✅ (2026-08-28)
README with the naming thesis, MIT license, this plan, doc templates, public GitHub repo.

### P1 — Local substrate (needs L1)
- [ ] vllm-mlx serving Qwen3-Coder-30B-A3B-4bit with continuous batching
- [ ] Tool-call soak test: 10+ turns, clean JSON every turn (S1)
- [ ] Throughput curve recorded: tok/s at 1K/16K/64K context (S7)
- [ ] `iogpu.wired_limit_mb` decision recorded (ADR if we raise it)
- [ ] Baseline spend measured: a normal day's work through OpenRouter, token distribution captured
- [x] ADR-005: local-provider abstraction; Apple-only v0 via packaging markers; cloud-only fallback off-Mac
- [ ] This setup codified as `soma local up` + `soma doctor --local` in P2 — the S1 spike graduates into doctor, so every installer runs the same verification we did
- **Exit:** local endpoint stable under 4+ concurrent streams; baseline cost report exists; EXP-001 (baseline) written

### P2 — The spine (needs L2, L4, L6)
- [ ] `uv`-managed package; `src/soma` layout; ruff + pytest wired
- [ ] Single agent on OpenHands SDK, LEAD tier, default tools
- [ ] Condenser on LOCAL (`max_size=80, keep_first=4`), **verified firing** (never assume the default)
- [ ] Telemetry v0: run ledger (`~/.soma/telemetry.db`) — one row per run: config hash, task fingerprint, outcome, tokens/cost per `usage_id`, duration
- [ ] `soma report costs` prints the ledger by `usage_id`
- **Exit:** one real task completed end to end; condensation event visible in the log; metrics split by usage_id; S3 verified (condenser on LOCAL while agent is on cloud)

### P3 — Differentiation (needs L5, L6)
- [ ] Archetype format: markdown + YAML frontmatter with our `tier:` key
- [ ] Agent factory: reads archetype → binds tier LLM → stamps `usage_id=agent:<name>`
- [ ] 10 representative agents ported (not 84); 10–20 highest-value skills symlinked
- [ ] Skill audit pass over everything wired to a shell (the ToxicSkills lesson: assume ~⅓ of unaudited skills have a flaw)
- **Exit:** same task run by two archetypes shows different behavior and separate cost lines

### P4 — Teams v0 (needs L7, L8)
- [ ] Delegation working: lead + 2 workers, fan-out/fan-in
- [ ] ADR-003: delegation substrate — DelegateTool vs owning one Conversation per agent (decide after S4)
- [ ] Beads wrapper tools: `bd_ready`, `bd_claim`, `bd_close`, `bd_create --deps discovered-from:`
- [ ] Discipline enforcement: pre-turn nudge injects "you have N ready beads" (hooks, not prompt hope)
- [ ] Bench suite v0: 3 small + 2 medium repeatable tasks with golden outcomes
- **Exit:** team completes a bench task where the lead never edits a file; delegation overhead multiplier measured (the ~7× trap, quantified for *us*)

### P5 — Signaling: the shared WAL (needs L2, L7)
- [ ] ADR-001: WAL substrate (recommendation: SQLite in WAL mode — see §5.2)
- [ ] Event schema v0 (Appendix B); publish/subscribe tools; per-agent cursors
- [ ] Inbox injection at turn boundaries ("3 new events for you: …")
- [ ] Chaos test: two conversations interleaving writes, no lost or doubled events (S5)
- **Exit:** success criterion 3 demonstrated — a handoff with no shared context; WAL contention retries tracked in telemetry

### P6 — Organizations (needs P4, P5)
- [ ] OrgPlan schema v0 (Appendix A) with inline custom archetypes
- [ ] Planner subagent (LEAD): goal → OrgPlan JSON; validate-and-retry loop on schema errors
- [ ] Org compiler: OrgPlan → team runtimes, comms topology, beads prefixes, budgets
- [ ] Orchestrator decision policy: solo vs org (see §5.1)
- [ ] Templates library: `solo`, `pair`, `review-pipeline`, `feature-team`, `two-team-hierarchy`
- [ ] `soma org run plan.yaml` and `soma run "goal"` (planner path)
- **Exit:** success criterion 2 attempted on bench-M in Docker; every org run writes a full replay bundle

### P7 — Sentinels (needs P2; informed by P4–P6 telemetry)
- [ ] Rule tier: OpenHands StuckDetector confirmed on
- [ ] Semantic tier on LOCAL: last ~20 events → `{stuck, confidence, reason}` every N events
- [ ] **Shadow mode first:** log verdicts for a week, no authority; measure precision/recall against hand labels
- [ ] Escalation ladder: observe → nudge → pause team → kill (apoptosis) → post-mortem episode into archetype memory
- [ ] Budget breakers: per `usage_id` and per org run
- **Exit:** EXP showing shadow-mode precision ≥ 0.8 before kill authority is armed

### P8 — Theory of mind (needs P2; parallel to P6–P7)
- [ ] InterlocutorModel (Appendix D) updated each turn by a LOCAL extraction pass
- [ ] Cognitive-style archetypes: analyst, socratic, explainer, critic, synthesizer (toolless, cheap)
- [ ] Router (LOCAL): which ≤2 styles does this turn need? Composer merges into the reply
- [ ] Shadow mode: log which styles *would* fire for a week of normal chat before enabling
- [ ] Blind A/B: 20 real turns, ToM-on vs ToM-off (success criterion 6)
- **Exit:** A/B result written up as an EXP, whatever the verdict

### P9 — Archetype memory (needs L9, P3)
- [ ] ADR-002: store — Mem0 (namespace = archetype) vs custom SQLite + LOCAL embeddings
- [ ] Write paths: `remember` tool; post-run reflection (LOCAL) → episode; consolidation "sleep" job promoting recurring lessons to semantic; procedural promotion drafts skill edits **behind a human review gate**
- [ ] Read paths: factory injects top-k relevant memories at instantiation ("prior experience" block); `recall` tool mid-run
- [ ] Hygiene: provenance on every memory, TTL/decay for episodic, per-archetype size caps
- [ ] Learning-curve harness: same archetype, same task class, 5+ runs, plot tokens/interventions
- **Exit:** success criterion 4 measured (positive or not — the curve is the deliverable)

### P10 — Hardening & scale-out (needs everything)
- [ ] Docker workspace default for unattended runs
- [ ] Security analyzer policies per archetype (auditors read-only, etc.)
- [ ] Port the remaining agents and skills (84/265 total) — only now
- [ ] Event-log retention policy enforced; canary task on a daily schedule
- [ ] Two-week cost verification (success criterion 5); v0.1 tag
- **Exit:** v0.1 released; all seven success criteria evaluated in a single report

---

## 5. Research track — the novel subsystems

### 5.1 Organizational orchestration

**Decision policy (v0, deliberately dumb):** the orchestrator asks LOCAL to classify the goal — estimated scope (files touched, parallelizable subtasks, review needs). Below thresholds → solo. Above → org path. The classifier's verdicts are logged and reviewed weekly; thresholds are tuned from data, not intuition.

**Org path:**

1. If the user supplied a design (YAML or prose), parse/validate it into an OrgPlan. Prose goes through the planner for formalization only.
2. Otherwise the **planner subagent** (LEAD tier) drafts an OrgPlan: teams, charters, hierarchy (`reports_to`), members by archetype, tiers, comms topology, beads prefixes, budgets, `done_when` criteria.
3. The planner may define **custom archetypes inline** (name, system prompt, tools, tier) when the library has no fit. Custom archetypes are schema-validated, get no shell access unless explicitly granted, and are flagged in the run report.
4. Validation is a loop: schema errors go back to the planner with the error text, max 3 retries, then fail loudly.
5. The **org compiler** turns the validated plan into runtimes: one Conversation per agent, comms subscriptions, beads namespaces, budget meters. Hierarchy = who may delegate to whom and who reports to whom via events.

**Guardrails:** global and per-team budget caps are mandatory fields. A plan without `done_when` is invalid. Team count and agent count have hard ceilings in config.

### 5.2 Communication fabric

Two layers with different subjects, deliberately not merged:

- **Beads = work state** (stigmergy — pheromone trails): what exists, what's ready, who claimed what, what got discovered. Durable, git-committed, queryable.
- **Shared WAL = signals** (cell signaling): messages, broadcasts, discoveries, artifacts, help requests, sentinel warnings, lifecycle events. Ephemeral-ish, per-run.

**Substrate (ADR-001 recommendation): SQLite in WAL mode.** One writer at a time with busy-retry, unlimited readers, real write-ahead-log semantics, trivially queryable for telemetry, single file per run. (JSONL + flock is the fallback if contention testing embarrasses SQLite; S5 decides.) The pun is free: our write-ahead log is a write-ahead log.

**Mechanics:**

- Every agent has a durable **cursor** per subscription (`org`, `team:<name>`, `agent:<self>`).
- Delivery is **at-least-once, pull-based at turn boundaries**: before an agent's next turn, the harness reads events past its cursors and injects a compact digest as an observation. No mid-turn interrupts (OpenHands serializes actions anyway).
- Agents also get `wal_publish` and `wal_read` tools for explicit use.
- **Spam guards:** per-agent publish rate limits; broadcasts to `org` require lead role; digests are summarized by LOCAL when > N events.

**Tests that matter:** the no-shared-context handoff (criterion 3); interleaved-writer chaos test (S5); a "gossip storm" test proving rate limits hold.

### 5.3 Theory-of-mind conversational layer

Two ideas fused: an explicit **model of the other mind**, and **inner delegation to cognitive styles** — conversation run as a small society of mind.

**InterlocutorModel** (Appendix D): goals, constraints, what they know, gaps/misconceptions, preferences, open threads (their unanswered questions, our unkept promises), register. Updated after every user turn by a LOCAL extraction pass. It is *memory-backed*: persisted per interlocutor, warm-loaded next session.

**Turn pipeline:**

1. **Update** the InterlocutorModel (LOCAL, async — never blocks the reply).
2. **Route** (LOCAL): given the turn + model, pick ≤ 2 cognitive styles from the registry: `analyst` (decompose, weigh trade-offs), `socratic` (surface the question behind the question), `explainer` (teach to the modeled knowledge level), `critic` (red-team the forming answer), `synthesizer` (compress, structure).
3. **Consult**: selected style agents run toolless on narrow context slices (WORKER or LOCAL tier), returning drafts/critiques/questions.
4. **Compose** (turn's main tier): one voice, informed by the consultations — never a stitched collage.
5. **Log** which styles fired, at what cost, and (in shadow mode) what the router *would* have picked. Routing policy improves from this data.

**Stretch — ToM between agents:** a team lead maintains lightweight models of its workers *from their WAL events alone* (what does worker-2 believe the goal is? is its recent event stream consistent with that?). Divergence between the lead's model and a worker's behavior is itself a sentinel signal. This generalizes the layer from human-facing chat to the whole organization.

**Evaluation:** blind A/B over 20 real turns (criterion 6), judged on: answered the actual question; anticipated a confusion; asked the *right* clarifier; respected known preferences.

### 5.4 Archetype memory

**The unit of memory is the archetype** (`security-auditor`), never the instance (`security-auditor#3`). Instances are somatic cells: they work, they die. What they learned survives in the type — epigenetics, not evolution (weights never change).

| Kind | Contents | Written by | Read by |
|---|---|---|---|
| **Episodic** | one record per run: task fingerprint, outcome, duration, cost, lessons, surprises | post-run reflection pass (LOCAL); apoptosis post-mortems | consolidation; instantiation top-k |
| **Semantic / long-term** | distilled durable lessons ("in pnpm monorepos, run X before Y") | consolidation "sleep" job promoting recurring episodic patterns (LOCAL, scheduled) | instantiation injection; `recall` tool |
| **Procedural** | learned heuristics that become executable — skill drafts, prompt-block edits | promotion pipeline, **human-gated** (a bad promotion poisons every future instance) | the archetype definition itself |
| **Temporal / periodic** | time-indexed metadata everywhere: recency weighting, decay, cadence notes ("release ritual, Fridays") | timestamps + decay scores on all of the above; the consolidation schedule itself | retrieval ranking |

**Read path:** at instantiation the factory queries the archetype's namespace for top-k memories relevant to the task fingerprint and injects a "Prior experience" block. Mid-run, `recall(query)` and `remember(fact)` tools, namespaced to the archetype.

**Hygiene (non-negotiable):** every memory carries provenance (run_id, task, source events). Episodic memories decay and are capped per archetype. Anything derived from *web content* is quarantined from procedural promotion — that's the prompt-injection-to-memory-poisoning path. Procedural promotion always passes human review.

**Store:** ADR-002 after L9. Start with Mem0 (namespace = archetype, extraction on LOCAL) unless the spike shows its extraction discards what we care about — then a custom SQLite + LOCAL-embeddings store (~300 lines) is Plan B. Benchmark on our episodes, not LOCOMO.

**The metric is a learning curve** (criterion 4). If archetype memory doesn't bend the curve, we delete it — the plan is falsifiable on purpose.

### 5.5 Sentinels

- **Rules tier (free):** OpenHands StuckDetector — verify it's on.
- **Semantic tier (LOCAL):** every N events, last ~20 events → "is this agent stuck?" → `{stuck, confidence, reason}`. Runs constantly; costs nothing but local watts.
- **Escalation ladder:** observe → nudge (inject a hint observation) → pause team → **apoptosis** (kill the instance, write the post-mortem episode, optionally respawn with the post-mortem in context) → escalate to human.
- **Budget breakers:** hard caps per `usage_id` and per org run; tripping one pauses the team and emits a WAL event.
- **Shadow first, always:** sentinels get authority only after a measured week (P7 exit criterion). A sentinel that kills productive agents is worse than no sentinel.

---

## 6. The lab bench — telemetry, experiments, analysis

The user requirement, verbatim: *we learn how it's doing and where it can improve as part of the design.* So measurement is a subsystem, not an afterthought.

### Principles

1. **Every run is an experiment.** Every invocation writes a ledger row keyed by a **config hash** (org plan + archetype versions + model tiers + prompt versions). Two runs are comparable iff their hashes say so.
2. **Ship dark.** New subsystems (sentinels, ToM router, memory injection) launch in **shadow mode**: they log what they *would* do, we measure against reality, then we arm them. Authority is earned with data.
3. **The event log is the flight recorder.** Any weird run = a replayable bundle (`runs/<id>/`: events, WAL, config, ledger row). `soma replay <run_id>` re-renders the whole thing; deterministic-ish re-execution (temperature 0 where possible) for debugging.
4. **Canaries catch drift.** A fixed seeded task runs daily against LOCAL and each cloud tier. Quantized-model regressions, provider model swaps, and prompt rot show up as canary deltas, not as mysterious Friday failures.
5. **Weekly instrument review.** One ritual: read `soma report costs|learning|sentinels|bench`, demote/promote agents across tiers, tune thresholds, file EXPs. Twenty minutes, every week, non-negotiable.

### 6.1 Telemetry substrate

- `~/.soma/telemetry.db` (SQLite): `runs`, `llm_calls` (per `usage_id`: tokens in/out, cached, cost, latency), `sentinel_verdicts` (shadow + armed), `condensations`, `tool_errors` (esp. malformed tool calls from LOCAL), `experiments`.
- Structured JSONL logs per run (`structlog`) — harness-level spans around every subsystem call.
- Optional: Langfuse for LLM-call tracing (ADR-004; self-hosted or free tier). Nice, not load-bearing — the SQLite ledger is the source of truth.

### 6.2 Metrics catalog (v0)

| Metric | Definition | Why it matters |
|---|---|---|
| Cost per task | ledger $ per completed bench/real task | the whole point |
| Local share | % of total tokens served by LOCAL | the M3's earn rate; target grows over time |
| Condenser effect | tokens sent with vs without condensation; cache-hit delta | the 2×-cost claim, verified on *our* workload |
| Tool-call malformation rate | malformed / total tool calls, per model | LOCAL quantization health; feeds canary |
| Delegation overhead | org-run tokens ÷ solo-run tokens on same bench task | the "7×" trap, quantified |
| WAL contention | busy-retries per 1K events | S5 verdict, ongoing |
| Sentinel precision/recall | armed-or-shadow verdicts vs hand labels | kill authority gate |
| Memory lift | learning-curve slope per archetype × task class | criterion 4 |
| ToM preference | blind A/B win rate | criterion 6 |
| Interventions | human unblocks per unattended run | autonomy, honestly measured |

### 6.3 Benchmark suite (`bench/`)

- **S/M/L repeatable tasks** with golden outcomes: S = single-file fixes in a fixture repo; M = multi-file feature with tests; L = a two-team org job. Fixture repos are vendored; tasks are prompts + `done_when` checks, runnable as `soma bench run S3 --label EXP-012`.
- **Conversation replay fixtures** for the ToM layer: recorded real dialogues re-run against candidate configurations.
- Bench runs after each build phase = our regression suite for *agent behavior*, not just code.

### 6.4 Experiment protocol

One page per experiment in `docs/experiments/EXP-NNN-title.md` ([template](docs/experiments/EXP-000-template.md)): hypothesis → variable → metric → n → result → **decision**. No experiment ends without a decision (adopt / reject / rerun-bigger). The ledger's `experiments` table links every contributing run.

### 6.5 Analysis

DuckDB straight over `telemetry.db` + JSONL for ad-hoc queries; four canned reports (`soma report costs|learning|sentinels|bench`). If a question gets asked three weeks running, it becomes a canned report.

---

## 7. Model routing & cost

Tiers as chosen in the reference doc — **re-verify the specific models at implementation time**; the tier *structure* is the commitment, the model names are not:

```python
LOCAL  = LLM(model="openai/mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit",
             base_url="http://localhost:8000/v1", usage_id="local")     # $0
WORKER = LLM(model="openrouter/<cheap-capable>",  usage_id="worker")    # bulk execution
LEAD   = LLM(model="openrouter/<frontier>",       usage_id="lead")      # orchestration, review
```

| Work | Tier |
|---|---|
| Orchestrator reasoning, org planning, architecture/security review | LEAD |
| Domain-agent execution (most archetypes) | WORKER |
| Condensing, pre-context extraction, classification, routing, sentinel checks, memory extraction/reflection, InterlocutorModel updates, commit messages | LOCAL |

Rules: every LLM instance gets a distinct `usage_id` (`agent:<name>`, `condenser`, `sentinel`, `tom:router`…). Budget breakers per §5.5. Weekly review demotes/promotes archetypes between tiers based on the ledger — the data decides, per agent, after a week of evidence.

Known cost traps carried forward: subagent-heavy workflows can run ~7× tokens (measure ours in P4); condensation invalidates prompt-cache prefixes (cheap on LOCAL, watch it on LEAD); pin LiteLLM far from the known-malicious 1.82.7/1.82.8 releases.

---

## 8. Assumption kill-list

Spikes that can invalidate the design run **first**, not when convenient.

| # | Assumption | Falsify by | If false |
|---|---|---|---|
| S1 | Quantized Qwen3-Coder emits clean tool calls over long sessions | 10+ turn soak, count malformations | different local model, or LOCAL demoted to non-tool work only |
| S2 | Per-subagent LLM independence works across mixed providers with separate Metrics | mixed local+OpenRouter delegation run | routing happens outside the SDK (own dispatcher); plan §5.1 unchanged, plumbing changes |
| S3 | Condenser can run on LOCAL while the agent runs on cloud | P2 config | condense on WORKER; local-share metric takes a hit |
| S4 | DelegateTool supports our team topology (addressable children, results fan-in) | L7 spike | org compiler owns one Conversation per agent; delegation becomes compiler-managed spawns (ADR-003) |
| S5 | SQLite WAL survives interleaved writers from concurrent conversations | chaos test, 2+ writers, 10K events | JSONL + flock, or a tiny event-broker thread in process 3 |
| S6 | Beads discipline is enforceable via wrapper tools + pre-turn nudges | P4 team run, count orphaned work | harness-level enforcement: no turn starts without a claimed bead |
| S7 | 96 GB sustains model + KV for ~10 streams + condenser traffic at usable tok/s | S1 under concurrent load | smaller model (Qwen3-8B) for LOCAL, or fewer concurrent locals |

---

## 9. Risks & traps

| Risk | Mitigation |
|---|---|
| LiteLLM supply-chain (1.82.7/.8 shipped malware) | pin versions; rotate creds if ever touched |
| Unaudited skills (~36% flaw rate in the wild) | P3 audit before shell access; least-privilege tools per archetype |
| Prompt injection → memory poisoning | web-derived memories quarantined; procedural promotion human-gated |
| Planner generates pathological orgs | schema validation, hard ceilings, mandatory budgets + `done_when`, templates as priors |
| Condenser silently off | explicit P2 check; telemetry row proves firing |
| V0/V1 docs confusion | only `/sdk/` URLs; noted in every mental-model doc |
| Event logs grow forever | retention policy in §2.3, enforced by P10 |
| WAL becomes a gossip firehose | rate limits, lead-only broadcasts, LOCAL-summarized digests |
| Sentinel false positives kill good agents | shadow mode + precision gate before authority |
| Unattended runs on bare metal | Docker default the moment nobody's watching |
| Metaphor-driven development | every subsystem must move a §6.2 metric or it gets cut — the biology names things, it doesn't justify them |

---

## 10. Milestones

| Milestone | Phases | Estimate (focused days) |
|---|---|---|
| M1: Local substrate proven | P1 | 0.5–1 |
| M2: Spine + telemetry v0 | P2 | 1–2 |
| M3: Differentiated archetypes | P3 | 1–2 |
| M4: First team + bench v0 | P4 | 2–3 |
| M5: WAL handoff demo | P5 | 2–4 |
| M6: First org run | P6 | 3–5 |
| M7: Sentinels armed | P7 | 1–2 (+1 shadow week elapsed) |
| M8: ToM A/B verdict | P8 | 3–5 |
| M9: Memory learning curve | P9 | 4–6 |
| M10: v0.1 | P10 | 3–5 |

Critical path: P1 → P2 → P4 → P5 → P6. P7–P9 parallelize after P5. Roughly 20–35 focused days; part-time, 6–10 weeks. Learning sessions interleave throughout (L-units gate the phases that need them).

---

## 11. Open questions (running list)

- Does OpenHands expose a pre-turn hook point, or do we wrap the Conversation loop for inbox injection and bead nudges? (L2/L7)
- Context slicing for ToM style agents: cheapest way to hand a style agent "just enough"? (P8)
- One Beads board per target repo with run-scoped labels, or per-run boards? (L8; leaning one board + labels)
- Where do org templates live once they stabilize — this repo or the target project's `.soma/`? (P6)
- Do we need Langfuse at all, or is the SQLite ledger + DuckDB enough? (ADR-004)

---

## Appendix A — OrgPlan schema v0

```yaml
version: 1
goal: "Ship dark mode across the web app; update docs; audit for regressions"
strategy: two_team_hierarchy        # solo | single_team | multi_team | <template>
global_budget_usd: 15               # mandatory
teams:
  - name: feature
    charter: Implement dark mode end to end
    lead: {archetype: tech-lead, tier: lead}
    members:
      - {archetype: implementer, count: 2, tier: worker}
      - {archetype: test-writer, tier: worker}
    subscribes: [team:feature, org]
    beads_prefix: feat
    budget_usd: 8                   # mandatory per team
    done_when:                      # mandatory
      - all beads under feat/* closed
      - CI green on branch
  - name: quality
    charter: Review diffs; hunt regressions; audit accessibility
    reports_to: feature.lead        # hierarchy edge
    members:
      - {archetype: reviewer, tier: worker}
      - archetype:                  # custom archetype, defined inline
          name: a11y-auditor
          tier: worker
          tools: [read, grep, browser]     # no shell unless explicit
          system_prompt: |
            You audit UI changes for WCAG 2.2 AA regressions. You never modify files.
    subscribes: [team:quality, team:feature, org]
    beads_prefix: qa
    budget_usd: 4
    done_when: [all qa/* beads closed]
routing_overrides: {condenser: local, extraction: local}
```

## Appendix B — Event schema v0 (shared WAL)

```sql
CREATE TABLE events (
  id       TEXT PRIMARY KEY,   -- ULID: sortable, unique
  ts       TEXT NOT NULL,
  run_id   TEXT NOT NULL,
  team_id  TEXT,
  sender   TEXT NOT NULL,      -- "archetype#instance", "orchestrator", "sentinel"
  kind     TEXT NOT NULL,
  audience TEXT NOT NULL,      -- 'org' | 'team:<name>' | 'agent:<id>'
  payload  TEXT NOT NULL,      -- JSON, kind-specific
  refs     TEXT                -- JSON array: bead ids, event ids, artifact paths
);
CREATE INDEX ix_events_cursor ON events(run_id, id);

CREATE TABLE cursors (
  subscriber TEXT NOT NULL,    -- agent instance id
  channel    TEXT NOT NULL,    -- subscription
  last_id    TEXT NOT NULL,
  PRIMARY KEY (subscriber, channel)
);
```

Kinds v0: `message`, `broadcast`, `discovery`, `artifact`, `help_request`, `decision`, `status`, `task_event` (mirrors bd claims/closes), `sentinel` (warnings, budget trips), `lifecycle` (spawned, killed, done).

## Appendix C — Episode schema v0 (archetype memory)

```yaml
archetype: security-auditor
run_id: 01J9…
ts: 2026-09-14T20:11:00Z
task_fingerprint: "audit auth module (fastapi, jwt)"
outcome: success            # success | partial | failure | killed
duration_s: 412
tokens: {local: 18_000, worker: 92_000, lead: 0}
lessons:
  - "This codebase keeps JWT config in settings.py, not env"
surprises:
  - "pytest fixtures monkeypatch the clock; token-expiry tests mislead"
artifacts: [reports/auth-audit.md]
refs: {events: [...], beads: [qa-014]}
provenance: reflection      # reflection | remember_tool | apoptosis
quarantined: false          # true if any source content came from the open web
```

## Appendix D — InterlocutorModel + style registry v0

```python
class InterlocutorModel(BaseModel):
    goals: list[str]          # what they're trying to achieve
    constraints: list[str]    # stated limits: time, stack, taste
    knows: list[str]          # concepts they've demonstrated
    gaps: list[str]           # misconceptions / unknowns worth addressing
    prefers: list[str]        # observed style preferences
    open_threads: list[str]   # their unanswered questions; our unkept promises
    register: str             # "focused, slightly rushed"
    updated_at: datetime
```

Styles v0 (toolless, cheap-tier): `analyst` — decompose, weigh; `socratic` — the question behind the question; `explainer` — teach to the modeled level; `critic` — red-team the forming answer; `synthesizer` — compress and structure. Router picks ≤ 2 per turn; the composer always writes one voice.

## Appendix E — Target repo layout

```
lambert-soma/
├── README.md · PLAN.md · LICENSE
├── pyproject.toml                  # uv-managed, py3.12+
├── docs/
│   ├── mental-models/              # Learn track output (01-…10-)
│   ├── decisions/                  # ADRs
│   └── experiments/                # EXP one-pagers
├── src/soma/
│   ├── orchestrator/ · org/ · comms/ · tom/ · memory/
│   ├── routing/ · sentinels/ · telemetry/ · archetypes/
│   └── cli.py
├── bench/                          # fixture repos + task specs + golden checks
├── spikes/                         # disposable proof code (S1–S7)
└── tests/
```

## Appendix F — Reference links

OpenHands SDK: [architecture](https://docs.openhands.dev/sdk/arch/sdk) · [doc index](https://docs.openhands.dev/llms.txt) · [condenser](https://docs.openhands.dev/sdk/guides/context-condenser) · [skills](https://docs.openhands.dev/sdk/guides/skill) · [file-based agents](https://docs.openhands.dev/sdk/guides/agent-file-based) · [delegation internals](https://deepwiki.com/OpenHands/software-agent-sdk/3.3-sub-agent-delegation-and-task-management) · [paper](https://arxiv.org/abs/2511.03690)
Local inference: [vllm-mlx](https://github.com/waybarrios/vllm-mlx) · [docs](https://vllm-mlx.is-a.dev/) · [MLX community models](https://huggingface.co/mlx-community)
Beads: [docs](https://steveyegge.github.io/beads/) · [repo](https://github.com/steveyegge/beads) · [molecules](https://github.com/steveyegge/beads/blob/main/docs/MOLECULES.md)
Memory: [Mem0](https://github.com/mem0ai/mem0) · [Letta](https://github.com/letta-ai/letta) (studied, not used)
