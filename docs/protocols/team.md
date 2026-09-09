# Team Protocol v0

*Status: DRAFT — awaiting human gate (Kushal) · governs Rung 2+ · PR-13.*
*Sources of authority: [ADR-010](../decisions/ADR-010-layer-doctrine.md) (team level + 2026-08-31 amendment) · [Cell Protocol](cell.md) (the contract this level serves) · PLAN §5.2 (dialogue lifecycle, communication fabric) · [EXP-004](../experiments/EXP-004-s11-beads-concurrency.md) (shared-board writes stall under concurrency).*

Rules are numbered for citation. The conformance harness ("team-in-a-box")
drives one team through its membrane with **scripted member cells**; when
harness and spec disagree, the spec wins or is consciously amended.

A team is the **provider side** of the cell protocol: everything a cell may
receive (briefing, notifications, invitations, roster and goal answers,
steering) is something a team emits, and everything a cell emits (progress,
discoveries, RESOLVED, death) is something a team reads. Nothing here reaches
inside a cell, and nothing here lets a team decide what a member does — it briefs, informs, messages, and provisions; the cell chooses.

## 0. Terms

- **Team** — a group of cells with one goal, one board subtree, one channel,
  and one output log. It is itself a cell from the outside (RC1).
- **Member** — a cell the team spawned. The team knows members by identity,
  archetype, and status — never by their internals.
- **Team board** — the team's Beads subtree: one epic for the team's goal,
  children for the work it pours. Members' own boards stay private.
- **Team channel** — `team:<id>` on the run's WAL. **Output log** — where the
  team reports upward; from above it looks like a cell's task log.
- **Journal** — the board's event stream (claim/close/create events),
  read scoped to the team's subtree.

## 1. Membrane (what a team may know)

- **TM1.** A team knows its members and only its members: identity,
  archetype, status (idle / on_task / in_dialogue / dead). It does not
  know member internals — prompts, Kind-1 logs, tool calls, model.
- **TM2.** A team knows nothing above itself: no other teams, no
  hierarchy, no orchestrator. What arrives from above arrives as a
  briefing on its own log (RC1); what it says upward leaves as events
  on its output log.
- **TM3.** Everything the team learns about members arrives as events:
  the journal (board) and member channels (WAL). It never polls a
  member's process or reads its bundle during life.
- **TM4.** *Testable:* a team-level module imports only from levels
  below it (cell, substrate); its prompt to any member contains only
  what the cell protocol allows (B3 layers, briefing, digests).

## 2. SPAWN & BRIEF

- **SP1.** A team spawns a member by minting a cell from an archetype
  (the factory) and writing the **briefing as the first entry of the
  member's task log** (cell B1). The team is the author of that event.
- **SP2.** A briefing states the member's task and names the team's
  goal; it never restates other members' work or internals.
- **SP3.** Spawning registers the member (registry, PR-14) with status
  `idle` until a claim exists (cell T1).

## 3. ASSIGN

- **AS1.** Assignment is **a bead plus a notification**: the team pours
  work onto its board subtree (epic + children; formulas arrive at
  Rung 3) and writes a task notification on the member's channel. The
  member claims (cell T1); the team never claims on a member's behalf.
- **AS2.** Shared-board writes go **through the harness, serialized**
  (EXP-004: correct but 25 s stalls under concurrent writers). Members
  never write the team board directly; their claims and closes travel
  via the scoped tools onto boards the team can observe.
- **AS3.** A member holds one task at a time (cell T2); the team queues
  further work as beads, not as extra briefings.

## 4. OBSERVE

- **OB1.** Progress is read from the **journal scoped to the team's
  subtree** (claims, closes, discovered-from beads) and from member
  channels (notes, discoveries, help requests, done, death).
- **OB2.** A discovered-from bead a member leaves is the team's to
  route: back to that member as a follow-up, to another member, or
  deferred. Discoveries are handoffs, not asides (cell T4).
- **OB3.** A member's `death` event (cell X1) is how the team learns a
  member ended, with its terminal status. Reflection is the rider's job,
  never the team's.

## 5. STEER

- **ST1.** When the team disagrees with a member's course, it **sends the
  member a message** — an event on the member's channel, delivered at
  the member's next turn boundary (never mid-step).
- **ST2.** Steering is **unbounded in count**: the team may message a
  member as many times as it judges useful. Messages are its only lever
  — it never edits a member's prompt, tools, or board, and never acts
  inside the member. Ending a task (a kill order, cell X1) remains
  available as a separate, explicit act.

## 6. CONVERSATIONS (cell-initiated; the team provisions, never directs)

- **BR1.** Conversations between members are **initiated by the members
  themselves** (cell D1: `start_dialogue` naming a sibling learned from
  the roster). The team never initiates, pairs, or directs a
  conversation between its members. Whether to talk, to whom, and
  about what is the cell's choice.
- **BR2.** On a member's request the team **provisions** the
  conversation: creates `dialogue:<id>`, widens both members'
  subscriptions to it, and delivers the invitation on the invitee's
  channel. Accepting is the invitee's choice (cell side).
- **BR3.** The team composes nothing and referees nothing about
  content. The exchange is back-and-forth for as long as the
  participants keep talking; the scheduler alternates their turns as a
  mechanical service, not a judgment.
- **BR4.** Parking (each participant's task bead blocked-on the dialogue
  bead, cell D2) is bookkeeping so a cell is never stepped in two
  activities at once — not a control.
- **BR5.** A conversation ends when a participant sends RESOLVED (cell
  D4). The safety cap and the circularity judge are harness safety
  nets against runaway loops — bounds on the worst case, grounded in
  dialogue-length data (PR-18b) — not team decisions about content.
- **BR6.** On termination the team runs the teardown: LOCAL writes a
  summary, the dialogue bead closes (unparking both), the summary —
  never the transcript — is injected into both task logs, and the
  channel is torn down (cell D5).

## 7. PROVIDE (provider side of cell C6–C8 — how cells find each other)

- **PV1.** The team exposes a **roster** members can query: each
  member's identity, archetype/role, a one-line description of what
  that role is for, and availability — nothing more (cell C6). This is
  how a cell discovers whom to ask.
- **PV2.** The team exposes its **current goal** to members (cell C7).
- **PV3.** The team exposes a way for a member to **address a message
  or question to a specific sibling** — the entry point that becomes a
  conversation (BR1) — without the team choosing the pairing.
- **PV4.** Transport is the team's implementation choice — SDK tools
  today; an MCP server exposing roster/goal/message is an equally valid
  carrier — the contract is what is exposed, not how.
- **PV5.** Answers exist only while the member is engaged in an
  activity; a cell with no team gets honest empty answers (cell C8).

## 8. LOG LIFECYCLE

- **LG1.** The team owns the logs it spins up: its team channel, every
  dialogue channel it creates, and its output log. It creates them on
  need and tears them down on completion.
- **LG2.** Member cell channels belong to the members; the team reads
  them and writes notifications, invitations, and corrections onto them.

## 9. COMPLETE (two gates)

- **CP1.** Gate one is **structural**: the team's epic closes on the board
  when all poured work is closed.
- **CP2.** Gate two is **evidential**: `judge_goal` audits the team's logs
  against its `done_when`. Pass → the result is written to the team's
  output log. Fail → the judge's `missing` items become new beads and
  work continues.
- **CP3.** The team reports progress upward as events on its output log
  throughout — a cell above sees it exactly as it would see any cell.

## 10. RECURSION

- **RC1.** From the outside **a team presents the cell contract**:
  briefing in, progress events out, result on its output log. Whoever
  spawned the team cannot tell it from a cell.
- **RC2.** Inter-team contact, the appointed leader, and deterministic
  succession are the leader addendum (Rung 3, ADR-010). Nothing in this
  document requires them.

## 11. Conformance (team-in-a-box)

The harness drives one team with **scripted member cells** — fakes that
emit protocol-shaped events (claim, note, discovery, done, death,
RESOLVED) on cue, no models — and asserts by rule:

| Check | Rules |
|---|---|
| spawn writes the member's briefing first, registers it idle | SP1 SP3 |
| assignment = bead on the subtree + notification on the channel; member claims | AS1 AS3 |
| shared-board writes serialized through the harness | AS2 |
| progress read from journal + channels only; no bundle reads during life | OB1 TM3 |
| discovered-from bead is routed by the team | OB2 |
| corrections delivered at the member's next turn boundary; count unbounded; never acts inside the member | ST1 ST2 |
| conversation: member-initiated; team provisions on request, never initiates or pairs; back-and-forth until RESOLVED; teardown | BR1–BR6 |
| roster with roles + direct addressing exposed; opaque beyond that; solo member gets empty answers | PV1–PV5 |
| two-gate completion: epic closed AND judge_goal pass → output log | CP1 CP2 |
| team behind the cell contract: briefing in, result out, indistinguishable | RC1 |
| import boundary: team modules import only downward | TM4 |

v0 of the harness lands with the rows implementable per PR: PR-14/15
(SP3, TM3), PR-16 (AS, OB), PR-17 (ST), PR-18 (BR), PR-19 (CP). Each PR
arms its rows and cites this spec.
