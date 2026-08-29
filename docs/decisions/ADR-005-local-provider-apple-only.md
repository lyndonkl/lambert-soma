# ADR-005 — Local-provider abstraction; Apple Silicon only in v0

*Date: 2026-08-28 · Status: accepted*

## Context

Lambert-Soma is open source. People who install it must be able to reproduce our local substrate — install the server, fetch the model, verify tool calling — without following a wiki page by hand. At the same time, we do not want to pay the cross-platform tax now (CUDA, ROCm, llama.cpp, Windows). The question: how do we make installation reproducible for others while keeping v0 scoped to Apple Silicon?

## Options

1. **Hardcode vllm-mlx everywhere.** Cheapest today. Every future backend becomes a grep-and-pray refactor, and platform checks leak into every module.
2. **`LocalProvider` interface, one implementation.** A small interface — `detect() / install() / download() / serve() / verify()` — with v0 shipping only `VllmMlxProvider`. Apple-only is enforced at the packaging level with a PEP 508 marker, not scattered `if` checks. Slightly more code now.
3. **Multi-backend from day one.** Correct in theory. In practice we'd be testing three inference stacks before the harness exists.

## Decision

Option 2. Concretely:

- The local tier is an optional extra: `pip install soma[local-mlx]`, whose dependency is declared as `vllm-mlx ; sys_platform == 'darwin' and platform_machine == 'arm64'`. Non-Apple machines cannot even install the wrong thing.
- `soma local up` runs the provider chain: detect platform → ensure venv deps → download the pinned model revision → start the server → health-check.
- `soma doctor --local` ships our verification suite — the S1 tool-call soak and a mini `bench-serve` throughput check. What we ran by hand in P1 is exactly what every installer runs. The spike *is* the recipe; the recipe becomes code.
- Off-Mac (or `--no-local`): the harness runs cloud-only. Work routed to LOCAL falls through to WORKER, with a warning and a visibly higher cost line in the ledger.
- Model choice, port, and revision live in config, not code — the provider consumes them.

## Consequences

Easier: onboarding ("two commands, then doctor tells you if your box is good"); adding future backends (a provider is a file, not a refactor); testing (doctor is CI-able on Apple runners). Harder: we maintain an interface with one implementation, and must resist letting vllm-mlx-isms leak through it — the interface is only as generic as its second implementation will prove.

## Revisit when

Someone actually wants a CUDA/llama.cpp provider; or vllm-mlx stalls as a project; or the cloud-only fallback turns out to be the common case (then the local tier's priority itself is in question).
