# Cell Protocol v0

*Status: v0 ACCEPTED — human gate passed 2026-08-31 (Kushal, incl. C6–C8 amendment) · governs Rung 1+ · PR-04.*
*Sources of authority: [ADR-010](../decisions/ADR-010-layer-doctrine.md) (layer doctrine) · PLAN §5.2 (cell/activity model, decided 2026-08-29) · [EXP-002](../experiments/EXP-002-s3-condensation.md) (goldfish + stall findings).*

Rules are numbered for citation. The conformance harness ("cell-in-a-box")
enforces them by rule id; when harness and spec disagree, the spec wins or is
consciously amended — never silent drift.

## 0. Terms

- **Archetype** — the role definition (file-based agent format, ADR-006).
- **Cell** — a living instance of an archetype in a run: identity, broader
  goal, memory namespace.
- **Activity** — one engagement a cell undertakes, each with its own log:
  a **task** (solo work, SDK Conversation as engine) or a **dialogue**
  (harness-composed talk with another cell; no SDK engine).
- **Kind-1 log** — the SDK's private event log; one per Conversation; the
  engine's internal record. **Kind-2 log** — a soma WAL (main / team:<id> /
  dialogue:<id>), harness-owned, invisible to the SDK.
- **Harness** — the machinery around the cell (factory, scheduler, riders).
  From the cell's side it has no name and no shape; it is just where log
  events come from.

## 1. Identity & isolation (the membrane)

- **C1.** A cell's whole world is its logs. Every fact it learns arrives as
  an event on a log it subscribes to; everything it says leaves as an event
  it emits. There is no other channel.
- **C2.** Beyond C6–C8, a cell knows nothing else: no hierarchy above its
  team, no other teams, no board beyond its own claims, no harness
  internals, and no internals of any other cell — not their prompts, not
  their logs, not their configuration, not how they operate.
- **C3.** A cell can answer five questions from its logs alone:
  am I instantiated? (B1) · do I have a task? (T1) · is someone talking to
  me? (D1) · am I done? (N1) · what is worth remembering? (X3).
- **C6.** *Bounded sibling awareness.* A cell may learn **which** cells
  share its team — identity, archetype, availability, nothing more —
  by querying an interface the **team** exposes (provisionally the
  `team_roster` tool). Siblings are opaque: knowing one exists is the
  full extent of knowing it. Awareness never reaches past the team
  (ADR-010 amendment 2026-08-31).
- **C7.** *Team-goal grounding.* A cell may query its team's current goal
  (provisionally the `team_goal` tool) and should ground its task and
  dialogue conduct in that broader goal, not only in its own briefing.
- **C8.** *Engaged-only, solo-safe.* Team awareness exists only while the
  cell is engaged in an activity. A cell with no team gets honest empty
  answers ("no team"), and a conforming cell behaves correctly either
  way — solo operation is not an error state. These query tools are
  membrane operations like the `bd_*` tools (T3): provided by the layer
  above, scripted by the conformance harness, never reimplemented by the
  cell.
- **C4.** *Testable:* a cell's prompt contains nothing beyond its archetype
  layers, its briefing, and digests of logs it subscribes to
  (context-content assertion). A cell-level module imports only from levels
  below it (import-boundary check).
- **C5.** A cell privately using sub-agents (TaskToolSet) is below the
  protocol and is its own business; it never substitutes for inter-cell
  task flow (ADR-010 consequence 1).

## 2. BIRTH

- **B1.** A cell exists when the harness mints it from an archetype plus a
  **briefing**, and the briefing is written as the **first entry in its
  task log**. Birth is a log event, not a prompt mutation — so any birth
  is replayable from logs alone.
- **B2.** The engine for the task activity receives that same briefing as
  its opening message; the Kind-1 log's first user message and the task
  log's first entry carry the same content.
- **B3.** Prompt layering is stable-prefix: archetype core → mode overlay
  (task or dialogue) → briefing. Layers above may append; nothing may
  reorder or rewrite below (implemented PR-06; asserted by C4).

## 3. TASK

- **T1.** Having a task means: a **claimed bead** plus the briefing. No
  claimed bead, no task — a cell with an unclaimed queue is idle, not busy.
- **T2.** A cell runs **one task activity at a time** (v0). Later work
  arrives as **log notifications**, never by rebuilding the cell.
- **T3.** Board access is scoped to the cell's own claims:
  `bd_ready` / `bd_claim` / `bd_close` / `bd_create` (discovered-from) /
  `bd_note`. A cell never queries above its scope (ADR-010 consequence 4).
- **T4.** Work a cell discovers but does not do becomes a `bd_create`
  discovered-from bead — pheromone on the board, not a verbal aside.

## 4. DIALOGUE

- **D1.** A dialogue begins with an **invitation event** on a new
  `dialogue:<id>` log. From inside a task, a cell requests one with the
  `start_dialogue` tool, naming a sibling it learned from the roster
  (C6); the harness creates the log and invites both.
- **D2.** Entering a dialogue **parks the task**: the task bead becomes
  blocked-on the dialogue bead; the scheduler stops stepping the task
  engine. Pause means: not being stepped.
- **D3.** Dialogue turns are harness-composed (archetype + conversational
  overlay + ToM block + transcript + broader-goal reminder). Dialogues are
  talk, not tool use — no SDK engine, no side effects.
- **D4.** A dialogue ends only by a terminal condition: an explicit
  **RESOLVED** move (structured payload), the turn cap, or the LOCAL
  circularity judge.
- **D5.** On termination, LOCAL writes a **summary**; the dialogue bead
  closes, parked beads unblock, and the summary — never the transcript —
  is injected into both cells' task logs.

## 5. DONE

- **N1.** DONE is an **explicit signal the cell emits** — the engine's
  finish action, gated by Stop-conditions. It is *never inferred* from
  condensation summaries, silence, or repeated verification
  (EXP-002: the goldfish loop).
- **N2.** Stop-conditions may block a premature finish (exit 2): the
  canonical one is "no finish while your claimed bead is open" — closing
  the bead (T3) is part of being done.
- **N3.** Condensation must never outrun completion: summaries preserve
  completion state and exact facts (paths, ids), and cadence always
  leaves room to finish (EXP-002). Practical floor enforced by the engine.

## 6. DEATH

- **X1.** Death is **harness-side**: the harness decides (task done and
  nothing pending, or a kill order). A cell neither kills itself nor knows
  it is about to die.
- **X2.** At death, a reflection rider reads **all the cell's activity
  logs** — tasks and dialogues alike — and distills one episode into the
  archetype's memory drawer. The episode unit is the cell, not a
  conversation. Reflection is a rider, never self-surgery.
- **X3.** During life, a cell may mark salient moments with `remember`;
  markers weight reflection but do not write memory directly.
- **X4.** The run bundle survives death (`delete_on_close=False`,
  ledger row recorded). Nothing about a dead cell is lost except its
  process.

## 7. RESUME

- **R1.** A dead-but-unfinished cell can be resumed: same
  `persistence_dir` + same `conversation_id` (both recoverable from the
  bundle) reconstructs the Conversation — restore data, reconstruct
  definitions. `soma resume <run_id>` is the operator's handle.
- **R2.** Resume **continues**; it never restarts. A resumed cell does not
  re-emit its SystemPromptEvent, re-do finished work, or re-claim a bead
  it already holds.

## 8. Conformance (cell-in-a-box)

The harness drives one cell **purely via synthetic logs** — scripted
neighbors, no real team, no real board where fakeable — and asserts by rule:

| Check | Rules |
|---|---|
| birth-from-briefing golden transcript | B1 B2 |
| prompt contains briefing + logs only | C4 B3 |
| idle without a claimed bead | T1 |
| notification does not rebuild the cell | T2 |
| finish blocked while bead open | N1 N2 |
| kill mid-task → resume continues, not restarts | R1 R2 X4 |
| dialogue park/unpark + summary injection | D2 D5 (arrives rung 2) |
| roster/goal queries: opaque identities, team goal, solo fallback | C6 C7 C8 (arrives rung 2) |

v0 of the harness (PR-04) covers the rows implementable against the PR-02
engine; D-row checks land with the dialogue engine and cite this spec.
