# EXP-003 — Archetype layer placement: dynamic context vs static prompt

*Date: 2026-09-01 · Runs: 20260901-2332xx…2344xx (ladder PR-06 proof runs) · Status: decided*

## Hypothesis

The archetype core + task overlay, delivered via the SDK's
`AgentContext.system_message_suffix` (rendered as the system message's
second content block, `dynamic_context`), steers cell behavior on the
local tier.

## Variable

Layer placement only: the SDK dynamic-context block vs the same text
composed into the static system prompt (`Agent(system_prompt=base +
core + overlay)`).

## Metric

Role adherence on an exact-content rule ("the greeting text must be
exactly: X"): does the produced file match the role's text?

## Setup

Local tier (Qwen3-Coder-30B-A3B-4bit, canonical serve flags). Two
fixture archetypes with opposing exact-content rules (`HELLO FROM
SOMA` vs `hello from soma`), same anchored task ("create greeting.txt
in your current working directory..."), `soma run --as <role>`.
Delivery verified by reading the run bundle's SystemPromptEvent.

## Result

**Dynamic block: 0/4 adherence.** Outputs were identical to a bare
proto-cell ("Hello Soma, welcome to the system!"), and one run
greeted as "Hello from OpenHands!" — the 15K-char preset identity
dominates. The block was provably DELIVERED (the bundle's
`dynamic_context` contains the role text verbatim); the model ignores
its placement.

**Static composition: adherence appears, noisily.** shouty: exact
match 2/2. quiet: 1/3 (two preset-fallback rolls, then role-driven
"Hello from soma" with casing drift). Placement is decisive;
precision on a 30B-4bit model remains probabilistic — no temperature
is pinned in the profiles, so sampling variance is in play.

Side observation, twice: cells wrote to `/tmp` despite the cwd
anchor. Workspace containment is prompt-level only until the
unattended/Docker rung — carried as a known gap.

## Decision

**adopt static composition** in `mint_agent` — it is also the better
fit for Cell Protocol B3: every cell of an archetype now shares a
byte-identical static prompt (a true stable prefix, and exactly what
per-archetype prefix caching wants). Re-run adherence on cloud tiers
once `OPENROUTER_API_KEY` is set; expect materially better precision.
Candidate future knob: pin temperature in tier profiles for cell
determinism.
