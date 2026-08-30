# ADR-009 — Org scaffolding: board + registry + two-gate completion

*Date: 2026-08-29 · Status: accepted (confirms D1, D2, D3 from the L8/L9 session)*

## Context

The harness must represent a self-referential hierarchy — solo agent, teams, sub-teams — and prove completion at every level. The L8 review showed Beads 1.1.0 ships most of the skeleton: nested epics/molecules, atomic claims, gates, swarms, and a transactional events journal.

## Decision

The organization is represented by **three synchronized structures**, each owning one kind of truth:

1. **OrgPlan** — the intent (teams, roles, tiers, comms, budgets, `done_when`). A validated document; static per run.
2. **Beads board** — the work. One board per run; the run is an epic; every team is a child epic/molecule; every sub-team is a child of a step. The hierarchy is a subtree, at any depth (D1: the org compiler emits a formula per team, pours a molecule, and runs the team as a swarm with the lead as coordinator).
3. **Cell registry** — the living. Harness-process state: cells, statuses, open Conversations, cursors. Ephemeral and rebuildable from the other two.

**Completion is two gates, at every level.** Structural: the epic closes on the board (blocked-parent semantics make this transitive). Evidential: `judge_goal` audits the events against `done_when`; a failed audit converts "what's missing" into new beads.

**The scheduler is the real main loop** — plain code, no LLM. It steps runnable Conversations, tails the events journal (D2) and the soma WAL with cursors, delivers inbox digests, refuses to step in-dialogue cells, runs sentinels between steps, and fires reflection on death.

**Conversations map one-to-one to activities.** The consumer talks to the orchestrator cell's Conversation; every other cell has its own. Nothing shares a context window; sharing happens through board, WAL, and memory.

**Dialogue pauses are graph edges.** A dialogue creates a bead that `blocks` the participant's task bead; closing it returns the task to the frontier. The pause is visible to the whole colony.

**Memory has altitudes but no team drawer.** Cells file episodes to their archetype's drawer; team lessons land in the lead's drawer plus project MEMORY.md (orchestrator sole writer, ADR-008); org-design episodes land in the planner archetype's drawer. Teams are positions, not species. D3: the store decision (ADR-002) is settled by spike S12 (Mem0 OSS evaluation).

## Consequences

Easier: completion, progress, and recursion come from Beads semantics we don't write; the journal gives telemetry and completion detection one tape. Harder: we depend on a young, fast-moving tool (pin versions; `bd doctor` in soma doctor); embedded Dolt is single-writer (spike S11 decides harness-serialized writes vs server mode); journal caveats (clone-local, per-replica seq, off by default) must be encoded in the tail consumer.

## Revisit when

S11 shows embedded mode can't take colony write load; or Beads' formula/swarm semantics diverge from what the compiler needs; or two-gate completion proves too slow (judge on every team close).
