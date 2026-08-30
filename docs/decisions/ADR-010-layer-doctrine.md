# ADR-010 — The layer doctrine: self-contained levels, logs as the only membrane

*Date: 2026-08-30 · Status: accepted (Kushal's doctrine, verbatim in spirit)*

## Context

Before building, Kushal set a structural rule: each level of abstraction must be treatable independently, with strict information hiding. A cell must not know the external world exists. A team must not know cell internals, other teams, or the wider hierarchy. The build must start at the bottom (cell behavior) and climb.

## Decision

**Levels, and what each may know:**

- **Cell.** Its whole world is its logs. Everything it knows arrives as events on logs it subscribes to. It exists: the birth briefing is the first entry in its task log. It has a task: a claimed bead plus that briefing. Someone is talking to it: an invitation event, then turn events on a dialogue log. It may finish: its Stop-hook conditions pass. It notes memories with `remember` for salient moments; systematic extraction is a harness rider at death, never self-surgery. It knows nothing else — no roster, no hierarchy, no teams.
- **Team.** Knows its members and only its members. It spawns and briefs them. It assigns work: a bead on the board plus a log notification. It observes progress via the journal, scoped to its subtree. It steers mid-task with an injected message when it disagrees. It brokers dialogues between its own members, and it owns the lifecycle of the logs it spins up and tears down. It does not know member internals. It does not know other teams or anything above itself.
- **Teams of teams.** Inter-team contact goes through a **leader**, and only through logs. Consensus is deliberately trivial. The leader is **appointed** at spawn, by the OrgPlan or the parent. Succession is **deterministic**: on leader death (detected as journal inactivity), the next member in the fixed member order takes over. Leadership is recorded as a label on the team's epic so it survives crashes. No voting, no rounds.
- **Recursion theorem.** From the outside, **a team presents the exact same contract as a cell**: briefing in, progress events out, result on its output log. That one property makes the hierarchy indefinitely composable — teams containing teams, agents containing agents — with no level aware of the shape above or below it. The orchestrator is just the root team's lead.

**Consequences for mechanisms already chosen:**

1. **TaskToolSet is demoted.** It is no longer inter-cell task transport (that would let a lead reach inside members synchronously). Inter-cell task flow is board + logs only. TaskToolSet remains available as a *cell-internal* helper — a cell privately using sub-agents is below the protocol and is its own business. Kill-list S4 is repurposed accordingly.
2. **Protocol specs become build artifacts.** `docs/protocols/cell.md` and `docs/protocols/team.md` (and the leader addendum) are written *before* their level is implemented, human-reviewed, and enforced by conformance harnesses ("cell-in-a-box", "team-in-a-box") that drive a level purely through its membrane.
3. **Isolation is tested, not promised.** Every rung ships layer-isolation proofs: context-content assertions (a cell's prompt contains nothing beyond its briefing and its logs) and an import-boundary check (a level's modules import only from levels below).
4. **Beads per level.** A cell sees only scoped board operations on its own claims (`bd_ready`/`bd_claim`/`bd_close`/`bd_create`). A team owns its epic/molecule subtree and reads the journal scoped to it. Leaders link across teams with cross-team beads and gates. No level queries the board above its scope.
5. **Build order is bottom-up.** The build plan is restructured into rungs: substrate → cell → team → teams-of-teams → cross-cutting riders → hardening. A rung starts only when the rung below passes its conformance suite.

## Consequences

Easier: each level is testable in a box with scripted neighbors; recursion falls out of one adapter (team-behind-cell-contract); failure isolation matches the membrane. Harder: log-based task handoff costs more latency than a function call (accepted — correctness of the membrane over speed); the team-as-cell adapter is new code the subsystem-major plan didn't have.

## Revisit when

Log-only transport proves too slow for tight inner loops (measure first — the ledger will say), or the trivial succession rule mishandles a real failure mode.
