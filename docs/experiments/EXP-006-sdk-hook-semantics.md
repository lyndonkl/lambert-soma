# EXP-006 — SDK hook semantics for Beads discipline

*Date: 2026-09-04 · Runs: e2e-pr09-hooks (proto-cell), e2e-pr09-hooks-arch, e2e-pr09-hooks-v2 (archetype cell) · Status: decided*

## Hypothesis

The OpenHands SDK's own hook system (`Conversation(hook_config=...)`)
can enforce Cell Protocol N1/N2/T1 — a cell cannot finish while its
claimed bead is open, and sees board state every turn — without any
prompt text carrying the rule.

## Variable

Enforcement mechanism: SDK command hooks (SessionStart,
UserPromptSubmit, Stop) vs nothing.

## Metric

A cell is told to finish WITHOUT closing its claimed bead. The Stop
hook must refuse (exit 2), and the refusal must reach the cell as
feedback. The cell must then close the bead and finish — visible in
the event log and on the board.

## Setup

Local tier, archetype cell (`tester`, terminal + file_editor; bd tools
mounted by the factory), one seeded ready bead on the cell's board.
Briefing: claim the bead, create done.txt, finish immediately, do NOT
close the bead. Hooks: `python -m soma.cli hook <event> --bundle <dir>`.

## Result

Final run (v2): SessionStart ok → UserPromptSubmit ok (digest injected)
→ `bd_claim cell-5u2` → file created → `finish` → **Stop hook
blocked=True exit=2**, feedback injected as an environment message
naming the bead → `bd_close cell-5u2` → `finish` → Stop hook
blocked=False exit=0. Board: in_progress `[]`, closed `[cell-5u2]`,
done.txt = ok. N1/N2 hold end to end.

Four semantics surprises, each now relied upon in `soma/hooks.py`:

1. **SessionStart context is recorded, not injected.** The SDK emits a
   `HookExecutionEvent` (not LLM-convertible) and injects nothing into
   the model's context at SessionStart; only UserPromptSubmit's
   `additionalContext` reaches the model (appended to the user
   message). So `bd prime` runs at SessionStart for the record, and the
   discipline text rides the first UserPromptSubmit digest instead.
2. **Hooks run with cwd = the cell's WORKSPACE, not the repo.** A
   relative bundle path in the hook command resolved against the
   workspace and pointed at a different board. Hook commands carry an
   absolute path.
3. **The bd tools key the board by the conversation dir
   (`<bundle>/<conversation id hex>`), not the run bundle.** Hooks keyed
   by the bundle looked at an empty board and let a claimed cell finish.
   `_make_conversation` now mints the conversation id up front and keys
   the hooks by the same conversation dir.
4. **In-memory claim state inside tool executors is lost between
   calls.** Live: `bd_claim` reported success, every `bd_close` said
   "claimed so far: none" — the SDK hands different executor copies to
   different calls. Fixed in `CellBoard`: the per-cell board is the
   truth (any in_progress bead on it is this cell's claim, T3 by
   construction); memory is a cache.

Also confirmed: exit 1 is a non-blocking error in the SDK contract; all
soma hook paths exit 0 or 2 (tested). The identity-less proto-cell
(`soma run` without `--as`) mounts no bd tools (PR-08 mounted them in
the factory only), so the Stop block cannot be exercised on it — a
plain cell has nothing to claim.

## Decision

**adopt** — SDK command hooks are the enforcement mechanism for cell
discipline. Carry forward: harness-side T1 (the briefing arriving with
a claimed bead) belongs to assignment (ladder PR-16); the proto-cell
should mount the same board tools as archetype cells or be retired
once archetypes are the only path (ladder PR-12/14).
