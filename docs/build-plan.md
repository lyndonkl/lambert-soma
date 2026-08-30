# Lambert-Soma — Build Plan (the PR ladder)

*Status: living · created 2026-08-29 · governs the build-out of the orchestration pipeline decided in ADR-005…009.*
*Companions: [PLAN.md](../PLAN.md) (phases, success criteria) · [implementation-plan.md](implementation-plan.md) (subsystem → SDK mechanism map).*

## Conventions (read once, apply to every PR)

- **One concept per PR.** Target ≤ ~400 net lines of product code (docs and test fixtures excluded). Reviewable in one sitting (≤ 30 min).
- **Every PR lands green and proves itself**: ships its tests, and where relevant extends `soma doctor` or `soma report`. The "Proof" column below is the review artifact.
- **No dead code.** Everything a PR adds is exercised by a CLI command, a test, or the next PR in the same milestone.
- **Spike PRs** ship a tracked report (`docs/experiments/EXP-*.md`) plus, if decisive, an ADR update. Spike scripts stay in the untracked `spikes/` directory.
- **PR description template**: Goal (1 line) · What's in · Proof · Out of scope.
- **Branches**: `mX-prNN-short-slug` (e.g. `ma-pr02-solo-cell`). Sizes: S ≈ <150 loc, M ≈ 150–400, L = must be split before opening.
- **Risk-first ordering**: every design-gating spike (S3, S4, S5, S8, S9, S11, S12) is embedded in the earliest PR that can run it.
- **Human gates**: skill-audit reports (PR-06), procedural skill promotions (PR-28), and arming sentinels (PR-23) require Kushal's explicit sign-off in the PR.

## Dependency shape

```
A(substrate) → B(archetypes) → C(beads spine) → E(scheduler+teams) → F(orgs) → G(sentinels)
                        └────→ D(WAL) ─────────↗                       ↘
                                         H(memory, after E)          J(hardening)
                                         I(ToM, after B; composer after E)
```
Parallelizable: C ∥ D after B · H ∥ F/G after E · I ∥ G/H.

## Milestone A — Substrate (PLAN P2)

| PR | Title | What lands | Proof | Size |
|---|---|---|---|---|
| 01 | Profiles & config | `soma init`: LLM profile store bootstrap (`local`/`worker`/`lead`), `soma.toml` (dirs, ports, run-mode policy); doctor checks profiles exist | doctor output snapshot test; unit tests on config load | S |
| 02 | Solo cell engine | `soma run "<task>"`: one Conversation + LocalWorkspace, persistence under `runs/<run_id>/`, condenser bound to `local` profile via `model_copy`, typed LLM-exception handling | E2E task on this repo; **S3 verified** — condensation event observed with agent on cloud profile | M |
| 03 | Telemetry ledger v0 | `~/.soma/telemetry.db` (`runs`, `llm_calls` per `usage_id` from `conversation_stats`); config hash via `OpenHandsAgentSettings` dump; `soma report costs` | golden report test; ledger row asserted after PR-02's E2E | M |

## Milestone B — Differentiation (P3)

| PR | Title | What lands | Proof | Size |
|---|---|---|---|---|
| 04 | Archetype loader + validation | `register_file_agents()` wiring + soma validation pass (frontmatter collisions, `metadata.soma_*` schema, tier profile exists); `soma archetypes list`; 3 seed archetypes (worker, explorer read-only, reviewer) | loader fixture tests incl. invalid files | M |
| 05 | Cell + factory + layering | `Cell` object (id, archetype, status); factory mints Agent with profile LLM, `usage_id=agent:<name>`; stable-prefix prompt layering (archetype core → mode overlay → briefing); `soma run --as <archetype>` | unit test on layer ordering; E2E: two archetypes, same task, different behavior + separate ledger lines | M |
| 06 | Skills wiring + audit gate | AgentSkills loading per archetype; `soma skills audit` (flags `` !`cmd` `` render-time execution, shell-risk lint); 5 pilot skills ported | audit fixture tests; **human gate: Kushal reviews the audit report in-PR** | M |

## Milestone C — Beads spine (P4a; lands D2)

| PR | Title | What lands | Proof | Size |
|---|---|---|---|---|
| 07 | Beads bootstrap | doctor: `bd` present + version pin; per-run `bd init` policy; events journal enabled per run; **S11 probe** (5 concurrent writers, embedded vs serialized) | S11 EXP report tracked; doctor snapshot | M |
| 08 | bd typed tools | `bd_ready`/`bd_claim`/`bd_close`/`bd_create` (discovered-from)/`bd_note` over the `--json` schema_version envelope; one shared bd-runner executor | tests against a temp board; malformed-JSON guard | M |
| 09 | Discipline hooks | SessionStart → `bd prime --hook-json`; Stop hook blocks finish while claimed bead open (**exit 2**); UserPromptSubmit injects ready-digest | hook scripts unit-tested on exit codes; E2E: cell cannot finish with open bead | M |
| 10 | Journal tail consumer | cursored tailer (`bd events tail --since`) → telemetry ingestion + scheduler event bus stub; 410-Gone re-baseline path | replay fixtures; truncation-path test | M |

## Milestone D — WAL signals (P5)

| PR | Title | What lands | Proof | Size |
|---|---|---|---|---|
| 11 | WAL store + tools | per-run SQLite: scoped channels (`main`/`team:*`/`dialogue:*`), cursors, ULIDs; `wal_publish`/`wal_read` tools sharing one connection executor; publish rate limits | **S5 chaos test** (interleaved writers, 10K events, none lost/doubled); gossip-storm rate-limit test | M |
| 12 | Inbox delivery | scheduler watcher → `send_message()`-while-running digests (**S8 ordering proof**); flagged fallback: harness-driven `step()` injection | E2E: two-cell handoff with **no shared context** (success criterion 3) | M |

## Milestone E — Scheduler & teams (P4b)

| PR | Title | What lands | Proof | Size |
|---|---|---|---|---|
| 13 | Cell registry + lifecycle | registry (statuses idle/on_task/in_dialogue), spawn/kill plumbing, `max_iteration_per_run` caps | unit lifecycle tests with `TestLLM` | M |
| 14 | Scheduler v0 | steps runnable Conversations; refuses in-dialogue cells; pause/resume plumbing | deterministic multi-cell scheduling tests (fake LLM) | M |
| 15 | TaskToolSet team | lead archetype with TaskToolSet; members registered from archetypes; **S4 verification** (resume by task_id, parallel=2) | bench-S E2E: lead never edits a file; delegation-overhead multiplier measured into ledger | M |
| 16 | Dialogue park/unpark | `start_dialogue` tool → dialogue bead `blocks` task bead; scheduler honors `in_dialogue`; close-bead unparks | graph-state tests; E2E pause visible in `bd blocked` | M |
| 17 | Dialogue turn engine | harness-composed alternating turns (direct `llm.completion`); RESOLVED via small response_schema; turn cap; LOCAL circularity judge; summary re-injection to both tasks | scripted dialogue with fake LLM; one live dialogue E2E | M |

## Milestone F — Organizations (P6; lands D1)

| PR | Title | What lands | Proof | Size |
|---|---|---|---|---|
| 18 | OrgPlan schema + templates | pydantic models + validation; templates `solo`/`pair`/`two-team`; user-YAML loader | fixture plans incl. invalid ones | M |
| 19 | Planner | planner archetype emits OrgPlan via `response_schema`; retry-on-invalid (max 3) | golden plans from canned tasks (fake LLM) + one live run | M |
| 20 | Org compiler → board | OrgPlan → run epic; per team: formula emit → `bd cook` → `bd mol pour` → `bd swarm create --coordinator`; cells registered; execution-hint metadata written | **board-shape golden test from fixture plan — no LLM calls needed** | M |
| 21 | Two-gate completion | journal "epic closed" → `judge_goal` vs team `done_when` → compose upward; fail → missing→new beads; `soma org run plan.yaml` | E2E: two-team fixture run to verdict; judge fail-path test | M |

## Milestone G — Sentinels & safety (P7)

| PR | Title | What lands | Proof | Size |
|---|---|---|---|---|
| 22 | Semantic sentinel (shadow) | event-callback checker → LOCAL endpoint (S10-aware: never via prompt-hook on non-local cells); verdicts table; shadow-only | precision/recall fixtures from canned loop transcripts | M |
| 23 | Escalation + budgets | ladder nudge→pause→kill (apoptosis → post-mortem episode stub); breakers per `usage_id` + per org; arming flag | ladder unit tests; **human gate: arm only after shadow-week EXP shows precision ≥ 0.8** | M |
| 24 | Docker unattended mode | DockerWorkspace run-mode policy; `NeverConfirm` + Ensemble(PolicyRail, Pattern) analyzers in-container; `ConfirmRisky` interactive | containerized bench E2E (success criterion 2 attempt) | M |

## Milestone H — Memory (P9; executes D3)

| PR | Title | What lands | Proof | Size |
|---|---|---|---|---|
| 25 | **SPIKE S12**: Mem0 OSS eval | local LLM config; embedder options (sentence-transformers vs served vs cloud); `infer=False` episodes + `infer=True` facts; recall/latency vs custom-store sketch | EXP report + **ADR-002 finalized** | M |
| 26 | Store adapter + episode write | `MemoryStore` interface + chosen impl; death-triggered reflection (LOCAL) reads all of a cell's activity logs → one episode (`agent_id`=archetype, kind, run/team metadata, expiration) | fixture logs → golden episodes | M |
| 27 | Birth injection | top-k retrieval at factory time → `<UNTRUSTED_CONTENT>`-wrapped "prior experience" block; per-archetype size caps | injection formatting tests; E2E memory visible in prompt | S |
| 28 | Sleep job | consolidation: episodes → semantic cards; procedural promotions opened as **draft skill PRs for human review**; expiry hygiene | consolidation fixtures; one generated draft-skill PR | M |
| 29 | Learning-curve harness | 5-run protocol per archetype × task class; `soma report learning` | success criterion 4 measured (curve is the deliverable, either direction) | M |

## Milestone I — Theory of mind (P8)

| PR | Title | What lands | Proof | Size |
|---|---|---|---|---|
| 30 | **SPIKE S9**: Tom storage | run Tom tools; inspect `user_model.json` schema, cadence, cost | EXP report + ADR-007 refinement | S |
| 31 | Interlocutor substrate | extend Tom user model; LOCAL per-turn updates in the main conversation | update-pass unit tests; persisted model round-trip | M |
| 32 | Style ensemble + router + composer | toolless style archetypes (analyst/socratic/explainer/critic/synthesizer); LOCAL router picks ≤2; composer writes one voice; **shadow-log router first** | router shadow-log EXP; composed-turn goldens (fake LLM) | M |
| 33 | ToM A/B harness | `fork()`-based same-history A/B; 20 real turns blind-rated | success criterion 6 EXP, whatever the verdict | M |

## Milestone J — Hardening (P10)

| PR | Title | What lands | Proof | Size |
|---|---|---|---|---|
| 34 | Canary + retention | daily seeded canary task (LOCAL + each cloud tier); runs/ retention policy enforcement | canary report rows; retention test | S |
| 35 | `soma top` | custom visualizer over registry + journal + WAL: live org view | manual demo recording | M |
| 36 | Library port batches | remaining archetypes/skills in repeated small PRs (audit-gated, ~10 per PR) | audit reports per batch | S× n |
| 37 | v0.1 | README refresh, all seven success criteria evaluated in one tracked report, tag | the v0.1 report | M |

## Success-criteria → PR map

| Criterion | Proven by |
|---|---|
| 1 daily driver | PR-02/05 onward, lived-in |
| 2 unattended org run | PR-24 |
| 3 no-shared-context handoff | PR-12 |
| 4 memory lift | PR-29 |
| 5 cost (fit-first, <$200/mo measured) | ledger from PR-03, verdict at PR-37 |
| 6 ToM A/B | PR-33 |
| 7 every subsystem has an EXP | enforced per milestone |
