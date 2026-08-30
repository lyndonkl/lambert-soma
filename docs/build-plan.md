# Lambert-Soma — Build Plan (the ladder)

*Status: living · restructured 2026-08-30 per ADR-010 (the layer doctrine) · supersedes the 2026-08-29 subsystem-major cut.*
*Companions: [PLAN.md](../PLAN.md) (phases, success criteria) · [implementation-plan.md](implementation-plan.md) (subsystem → SDK mechanism map) · [ADR-010](decisions/ADR-010-layer-doctrine.md) (why this shape).*

## The shape: rungs, not subsystems

We build **bottom-up by abstraction level**. A rung starts only when the rung below passes its conformance suite. Each level is developed and tested *in a box*, driven purely through its membrane (its logs), with scripted neighbors.

```
Rung 0  Substrate            (level-neutral prerequisites)
Rung 1  THE CELL             (a cell's whole world is its logs)
Rung 2  THE TEAM             (manages members; knows nothing above)
Rung 3  TEAMS OF TEAMS       (leaders, recursion, the org compiler)
Rung 4  RIDERS               (sentinels, memory, ToM — attach per level)
Rung 5  HARDENING            (canary, visualizer, library port, v0.1)
```

## Conventions (read once, apply to every PR)

- **One concept per PR.** Target ≤ ~400 net lines of product code (docs and test fixtures excluded). Reviewable in one sitting (≤ 30 min).
- **Every PR lands green and proves itself**: ships its tests; extends `soma doctor` / `soma report` where relevant. The "Proof" column is the review artifact.
- **Layer-isolation invariant (new, per ADR-010).** Every rung ships isolation proofs: (a) context-content assertions — a cell's prompt contains nothing beyond its briefing and its logs; (b) an import-boundary test — a level's modules import only from levels below.
- **Protocol specs are human-gated.** `docs/protocols/*.md` are written before their level is implemented and reviewed by Kushal in their own PR.
- **No dead code.** Everything a PR adds is exercised by a CLI command, a test, or the next PR in the same rung.
- **Spike PRs** ship a tracked report (`docs/experiments/EXP-*.md`) plus, if decisive, an ADR update. Spike scripts stay in untracked `spikes/`.
- **PR description template**: Goal (1 line) · What's in · Proof · Out of scope.
- **Branches**: `rN-prNN-short-slug` (e.g. `r1-pr04-cell-protocol`). Sizes: S ≈ <150 loc, M ≈ 150–400, L = split before opening.
- **Human gates**: protocol specs (PR-04, 13, 20), skill audits (PR-07), procedural promotions (PR-32), sentinel arming (PR-27).

## Rung 0 — Substrate (PLAN P2)

| PR | Title | What lands | Proof | Size |
|---|---|---|---|---|
| 01 | Profiles & config | `soma init`: LLM profile store (`local`/`worker`/`lead`), `soma.toml`; doctor checks profiles | doctor snapshot test; config unit tests | S |
| 02 | Proto-cell engine | `soma run "<task>"`: one Conversation + LocalWorkspace, persistence under `runs/<run_id>/`, condenser on `local` profile, typed LLM-exception handling. (No protocol yet — this is the engine the protocol will wrap.) | E2E task; **S3 verified** — condensation on local while agent on cloud | M |
| 03 | Telemetry ledger v0 | `~/.soma/telemetry.db` (`runs`, `llm_calls` per `usage_id`); config hash via `OpenHandsAgentSettings`; `soma report costs` | golden report; ledger row asserted after PR-02 E2E | M |

## Rung 1 — THE CELL

*Exit criterion: one cell passes the full lifecycle conformance suite driven only by logs, plus isolation proofs.*

| PR | Title | What lands | Proof | Size |
|---|---|---|---|---|
| 04 | **Cell Protocol spec + cell-in-a-box** | `docs/protocols/cell.md`: BIRTH (briefing = first task-log entry) · TASK (claimed bead + briefing; later tasks as log notifications) · DIALOGUE (invitation event, turn events, RESOLVED emission) · DONE (Stop-conditions) · DEATH (harness-side reflection trigger; `remember` for salient moments). Conformance harness that drives one cell purely via synthetic logs | **human gate: spec review**; harness runs against PR-02 engine with golden transcripts | M |
| 05 | Archetype loader + validation | `register_file_agents()` + soma validation (collisions, `metadata.soma_*`, tier profile exists); `soma archetypes list`; 3 seed archetypes | loader fixtures incl. invalid files | M |
| 06 | Cell + factory + layering | `Cell` object; factory mints Agent with profile LLM, `usage_id=agent:<name>`; stable-prefix layering (archetype core → mode overlay → **birth briefing per spec**) | layer-order unit test; two archetypes differ E2E; **isolation proof: prompt contains briefing + logs only** | M |
| 07 | Skills wiring + audit gate | AgentSkills loading; `soma skills audit`; 5 pilot skills | audit fixtures; **human gate: audit report** | M |
| 08 | Cell-side Beads | doctor `bd` checks + version pin; per-run `bd init`; journal enabled; typed tools `bd_ready`/`bd_claim`/`bd_close`/`bd_create`(discovered-from)/`bd_note` over `--json` envelope, scoped to own claims; **S11 probe** (5 concurrent writers) | temp-board tests; malformed-JSON guard; S11 EXP report | M |
| 09 | Discipline hooks | SessionStart → `bd prime --hook-json`; Stop blocks finish with open bead (**exit 2**); UserPromptSubmit ready-digest | exit-code unit tests; E2E: cell cannot finish with open bead | M |
| 10 | Cell WAL participation | per-run SQLite WAL: scoped channels, cursors, ULIDs; `wal_publish`/`wal_read` (subscribed channels only); rate limits | **S5 chaos test** (interleaved writers); gossip-storm test | M |
| 11 | Cell dialogue participation | cell side only: receive invitation on inbox, accept, respond to turn events, emit RESOLVED via small response_schema; honors parked state | scripted dialogue against cell-in-a-box (no real peer needed) | M |
| 12 | Cell death & memory points | finish protocol; `remember()` tool against a `MemoryStore` interface (stub impl); reflection trigger emitted at death (store lands Rung 4); conformance suite extended to full BIRTH→DEATH | full-lifecycle golden transcript; isolation proofs re-run | M |

## Rung 2 — THE TEAM

*Exit criterion: one team of 2–3 cells completes a bench task; team modules import nothing from Rung 3; member contexts contain no roster beyond what the protocol allows.*

| PR | Title | What lands | Proof | Size |
|---|---|---|---|---|
| 13 | **Team Protocol spec + team-in-a-box** | `docs/protocols/team.md`: spawn/brief · assign (bead + log notification) · observe (journal scoped to subtree) · steer mid-task (injected message on disagreement) · broker dialogues between own members · log lifecycle (create/tear down channels) · report result to own output log. Harness with scripted member cells | **human gate: spec review**; harness golden runs | M |
| 14 | Registry + lifecycle | cell registry (idle/on_task/in_dialogue), spawn/kill plumbing, `max_iteration_per_run` caps | lifecycle tests with `TestLLM` | M |
| 15 | Scheduler v0 | steps runnable Conversations; refuses in-dialogue cells; pause/resume | deterministic multi-cell tests (fake LLM) | M |
| 16 | Assignment + observation | team pours tasks (epic + children; formulas arrive in Rung 3); members claim; **journal tail consumer** (cursored, 410 re-baseline) powers team observation + telemetry ingestion | replay fixtures; board-driven assignment E2E | M |
| 17 | Mid-task steering + inbox | scheduler watcher → `send_message()`-while-running digests (**S8 ordering proof**); steering = team injects a correction into a member | E2E: **no-shared-context handoff (success criterion 3)**; steering changes member behavior | M |
| 18 | Dialogue brokering | team creates dialogue channels between own members; dialogue bead `blocks` task beads; harness alternates turns; turn cap; LOCAL circularity judge; summary re-injection; teardown | scripted + one live dialogue E2E; `bd blocked` shows the pause | M |
| 19 | Team completion, two gates | journal "epic closed" → `judge_goal` vs `done_when` → result written to team's output log; fail → missing→new beads | two-gate E2E incl. judge fail-path | M |

## Rung 3 — TEAMS OF TEAMS

*Exit criterion: a two-team fixture with one nested sub-team runs end to end; import-boundary check passes across all levels.*

| PR | Title | What lands | Proof | Size |
|---|---|---|---|---|
| 20 | **Leader & recursion spec** | leader addendum to protocols: appointed at spawn; deterministic succession (fixed member order) on journal-inactivity; leadership as epic label; inter-team channels leader-only. **Recursion theorem: a team presents the cell contract externally** | **human gate: spec review** | S |
| 21 | Team-as-member adapter | wrap a team runtime behind the cell protocol (briefing in → progress events → result on output log) | recursion E2E: team containing a sub-team, driven by team-in-a-box | M |
| 22 | OrgPlan schema + templates | pydantic + validation; `solo`/`pair`/`two-team` templates; user-YAML loader | fixture plans incl. invalid | M |
| 23 | Planner | planner archetype emits OrgPlan via `response_schema`; retry-on-invalid (max 3) | canned-task goldens (fake LLM) + one live | M |
| 24 | Org compiler → board | OrgPlan → root team + nested teams via the same spawn path; per team: formula emit → `bd cook` → `bd mol pour` → `bd swarm create --coordinator`; execution-hint metadata | **board-shape golden test from fixture plan — zero LLM calls** | M |
| 25 | Root run | `soma org run plan.yaml`; `soma chat` orchestrator = the root team's lead; top-level two gates | two-team + sub-team fixture to verdict | M |

## Rung 4 — RIDERS (attach per level)

| PR | Title | Attaches at | What lands | Proof | Size |
|---|---|---|---|---|---|
| 26 | Semantic sentinel (shadow) | cell | event-callback checker → LOCAL (S10-aware); verdicts table; shadow-only | precision fixtures from canned loop transcripts | M |
| 27 | Escalation + budgets | cell + team | nudge→pause→kill (apoptosis → post-mortem episode); breakers per `usage_id` + per org; arming flag | ladder tests; **human gate: arm after shadow-week precision ≥ 0.8** | M |
| 28 | Docker unattended mode | run | DockerWorkspace policy; `NeverConfirm` + Ensemble analyzers in-container; `ConfirmRisky` interactive | containerized bench E2E (**success criterion 2**) | M |
| 29 | **SPIKE S12**: Mem0 OSS eval | store | local LLM config; embedder options; infer modes; recall/latency vs custom sketch | EXP + **ADR-002 finalized** | M |
| 30 | Store adapter + episodes | cell death | `MemoryStore` impl per ADR-002; reflection reads all of a cell's activity logs → one episode (infer=False, expiration) | fixture logs → golden episodes | M |
| 31 | Birth injection | cell birth | top-k → `<UNTRUSTED_CONTENT>`-wrapped prior experience; per-archetype caps | formatting tests; E2E visible in prompt | S |
| 32 | Sleep job | store | episodes → semantic; procedural promotions as **draft skill PRs (human gate)**; expiry hygiene | consolidation fixtures; one draft-skill PR | M |
| 33 | Learning-curve harness | lab bench | 5-run protocol; `soma report learning` | **success criterion 4** measured | M |
| 34 | **SPIKE S9**: Tom storage | main convo | inspect `user_model.json` schema/cadence/cost | EXP + ADR-007 refinement | S |
| 35 | Interlocutor substrate | main convo | extend Tom model; LOCAL per-turn updates | round-trip tests | M |
| 36 | Style ensemble + router + composer | main convo | toolless styles; LOCAL router ≤2; composer one voice; shadow-log first | shadow EXP; composed-turn goldens | M |
| 37 | ToM A/B harness | lab bench | `fork()` same-history A/B, 20 turns blind | **success criterion 6** EXP | M |

## Rung 5 — HARDENING

| PR | Title | What lands | Proof | Size |
|---|---|---|---|---|
| 38 | Canary + retention | daily seeded canary (LOCAL + cloud tiers); runs/ retention | canary rows; retention test | S |
| 39 | `soma top` | visualizer over registry + journal + WAL | demo recording | M |
| 40 | Library port batches | remaining archetypes/skills, ~10 per PR, audit-gated | audit reports per batch | S× n |
| 41 | v0.1 | README refresh; all seven success criteria in one tracked report; tag | the v0.1 report | M |

## Live-tooling notes (dogfooding, 2026-08-30)

- The ladder now LIVES on this repo's beads board: root epic `lambert-soma-bad`, one child epic per rung, one task per PR, 42 blocks-edges. `bd ready` is the source of truth for what to build next (only PR-01 is ready at start). Rung epics are deliberately NOT chained — a blocked parent blocks its children, which would over-constrain the riders' cross-links (e.g. the Mem0 spike unlocks after Rung 1, not Rung 3).
- Installed `bd 1.2.2` (Homebrew core; Dolt bundled). **Deviation from the 1.1.0 docs: the `bd events` journal CLI does not exist in 1.2.2** (`bd config set events-journal true` is accepted but flagged unrecognized). PR-16's observation mechanism must be probed against the installed version — candidates: a newer bd release, `bd serve`'s HTTP feed, or polling `bd list --json` diffs. Pin the bd version in doctor either way.
- Issue prefix is `lambert-soma-*` (from repo name); children get dotted ids (`lambert-soma-bad.1.1` = PR-01).
- `bd init` self-committed its config (AGENTS.md, CLAUDE.md managed section, `.claude/settings.json` SessionStart hook → `bd prime`, `.agents/skills/beads/SKILL.md`, `.beads/` tracked config). The beads SKILL.md plugs directly into our SDK skill loading later.

## Notes vs the 2026-08-29 cut

- **TaskToolSet removed from the ladder** (was PR-15): per ADR-010 it is cell-internal only, never inter-cell transport. Kill-list S4 repurposed. If a cell later wants private sub-agents, that's a small rider PR.
- **Protocol specs + in-a-box harnesses added** (PR-04, 13, 20) — the doctrine's enforcement mechanism.
- **Journal tail moved to Rung 2** (team observation is its consumer); WAL and dialogues split into cell-side (Rung 1) and team-side (Rung 2) halves.
- **Leader succession added** (PR-20/21); the orchestrator is now explicitly the root team's lead — Rung 3 is mostly "apply Rung 2 recursively."

## Success-criteria → PR map

| Criterion | Proven by |
|---|---|
| 1 daily driver | PR-02/06 onward, lived-in |
| 2 unattended org run | PR-28 |
| 3 no-shared-context handoff | PR-17 |
| 4 memory lift | PR-33 |
| 5 cost (fit-first, <$200/mo measured) | ledger from PR-03, verdict at PR-41 |
| 6 ToM A/B | PR-37 |
| 7 every subsystem has an EXP | enforced per rung |
