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

Forced arm: **3 Condensation events** (8, 7, 7 events summarized), loop
kept running after each. Ledger split cleanly: `local` (agent)
125,321 prompt / 1,840 completion tokens; `condenser` 8,172 prompt /
1,113 completion tokens; both cost 0.0.

Surprises, both load-bearing:

1. **Goldfish loop.** The agent completed the task in 4 actions, but at
   `max_size=8` each condensation replaced its recent memory with a
   summary that did not clearly say "task already done". It re-verified,
   then re-created the file, and burned all 25 iterations
   (`error`: max-iterations). Aggressive condensation converts a
   finished task into an infinite one. The engine now refuses
   `--condense-at < 8` (SDK invariant) but the practical floor is far
   higher; summaries must carry completion state — a requirement for
   the Cell Protocol's DONE design (PR-04).
2. **25-minute stall window.** A hung provider call sits behind SDK
   defaults `timeout=300s × 5 retries` before any exception. One run
   froze 13+ min on a single call while the server answered fresh
   probes. The engine now clamps both LLMs to `timeout=120s,
   num_retries=2`, so a dead call surfaces as typed `error:timeout` in
   minutes.

Clean arm (default 240): no condensation on a short task; run finishes.

## Decision

**adopt** — condenser on the local tier with its own `usage_id` is the
standard cell wiring (zero-cost summarization, separately metered).
Carry into PR-04: condensation summaries must preserve "what is already
done"; never tune `max_size` low enough to outrun task completion.
Cloud-agent variant (agent on `worker`, condenser local) is a
one-command rerun once `OPENROUTER_API_KEY` is set; the mechanism does
not depend on which tier the agent rides.
