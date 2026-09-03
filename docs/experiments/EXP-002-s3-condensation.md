# EXP-002 — S3: condenser as a separate, separately-metered LLM

*Date: 2026-08-30 · Runs: 20260830-235442-d978e7 (forced), 20260830 clean E2E · Status: decided*

## Hypothesis

The SDK condenser can run on a different LLM than the agent (local tier,
own `usage_id`), fire mid-run without breaking the loop, and appear as
its own line in `conversation_stats`.

## Variable

`--condense-at 8` (pathologically low, to force condensation on a short
task) vs the SDK default `max_size=240`.

## Metric

Presence of `Condensation` events in the run bundle + a separate
`condenser` entry in `usage_to_metrics` with zero cost. Threshold: at
least one condensation with the run still progressing afterward.

## Setup

Proto-cell engine (PR-02), task "create haiku.txt, confirm with ls,
read it back", agent tier = `local` (cloud key not yet configured),
condenser = `local` profile rebadged `usage_id="condenser"` via
`model_copy`, vllm-mlx server with canonical flags, max 25 iterations.

## Result

Forced arm: **6 Condensation events** (forgetting 8 events, then 7 five
times — bundle events 10/17/24/31/38/45), loop kept running after each. Ledger split cleanly: `local` (agent)
125,321 prompt / 1,840 completion tokens; `condenser` 8,172 prompt /
1,113 completion tokens; both cost 0.0.

Surprises, both load-bearing:

1. **Goldfish loop — and the mechanism is subtler than "summary lost
   the done-fact".** The summaries were GOOD: every one said
   `COMPLETED: ... PENDING: None ... No further action is required`.
   The loop persisted anyway, for three compounding reasons visible in
   the event log:
   - A run only ends when the agent CALLS the `finish` tool (the clean
     run ends exactly that way). A summary asserting "done" is context,
     not termination.
   - Faced with second-hand completion ("the summary says I finished")
     instead of its own recent observations, the 30B coder model chose
     to re-verify rather than call `finish` — and each verification
     burst re-crossed `max_size=8` before it got there. Condensation
     cadence outran the finish opportunity.
   - Later summaries drifted factually: the file path lost its
     `/e2e-ws` segment, so re-create attempts failed with "Invalid
     `path` parameter", manufacturing genuine new uncertainty.
   The engine refuses `--condense-at < 8` (SDK invariant) but the
   practical floor is far higher. Requirements carried to the Cell
   Protocol (PR-04): DONE must be a structural signal the cell emits
   (finish/stop conditions), summaries must preserve exact facts
   (paths!), and condensation cadence must always leave room to finish.
2. **25-minute stall window.** A hung provider call sits behind SDK
   defaults `timeout=300s × 5 retries` before any exception. One run
   froze 13+ min on a single call while the server answered fresh
   probes. The engine now clamps both LLMs to `timeout=120s,
   num_retries=2`, so a dead call surfaces as typed `error:timeout` in
   minutes.

Clean arm (default 240): no condensation on a short task; run finishes.

**Cloud arm (2026-09-03, agent on `worker` = DeepSeek V4 Pro, condenser
still local, `--condense-at 8`):** S3 holds — 6 Condensation events,
ledger split `worker` 123,814 prompt / 2,770 completion tokens
($0.034) vs `condenser` 6,357 / 298 ($0.00). And the **goldfish loop
reproduces on a strong model**: a six-step task (echo a…e, then ls) got
to d, condensation fired, and the agent restarted at `echo a` — six
cycles of a/b/c until max-iterations, never reaching e. The loop is
structural, not a weak-model artifact: at this cadence no model can
recover "which step am I on" from the summary. This is the hard
version of the PR-04 requirement (summaries must carry progress state;
cadence must never outrun completion). A short haiku task on the same
tier finished in 3 calls / 7 events — below the threshold, no
condensation, clean finish.

## Decision

**adopt** — condenser on the local tier with its own `usage_id` is the
standard cell wiring (zero-cost summarization, separately metered).
Carry into PR-04: DONE is a structural signal the cell must emit
(finish/stop conditions), not something inferred from summaries;
summaries must preserve exact facts; never tune `max_size` low enough
to outrun completion.
Cloud-agent variant (agent on `worker`, condenser local) is a
one-command rerun once `OPENROUTER_API_KEY` is set; the mechanism does
not depend on which tier the agent rides.
