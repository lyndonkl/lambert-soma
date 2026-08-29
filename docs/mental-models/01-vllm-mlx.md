# 01 — vllm-mlx

*Session date: 2026-08-28 · Docs digested: GitHub README, PyPI page (v0.4.1), model card — deeper docs-site pass pending*
*Status: **draft** — capability map done; spike results and Q&A pass still to land.*

## One-sentence essence

vllm-mlx keeps one MLX model resident in unified memory and shares it across many HTTP clients with vLLM-style scheduling — continuous batching plus a paged, prefix-shared KV cache — behind both OpenAI and Anthropic APIs from a single process.

## The core abstractions

- **Engine vs API layer.** One inference engine (scheduler + KV manager) sits under two API surfaces: OpenAI (`/v1/chat/completions`, `/v1/completions`, `/v1/embeddings`, `/v1/rerank`, `/v1/responses`) and Anthropic (`/v1/messages`). Same weights, same cache, two dialects.
- **Continuous batching.** Requests join and leave the batch one token at a time. A short classifier call does not queue behind a long condensation. This property is what makes one server per colony viable.
- **Paged KV + prefix trie.** KV cache lives in fixed pages; a trie shares identical prefixes across requests. For us: design LOCAL prompts prefix-first — one long shared system prefix, variable content at the tail — so concurrent agents pay for the prefix once.
- **MoE economics.** Qwen3-Coder-30B-A3B: 31B parameters resident (~17.2 GB at 4-bit), ~3B active per token. Memory cost of a 30B, decode speed closer to a 3B. That trade is why this model fits the mechanical tier.

## What Lambert-Soma uses it for

The entire LOCAL tier (`soma.routing`): condensation, pre-context extraction, classification and routing decisions, sentinel loop checks, memory reflection and consolidation, InterlocutorModel updates. Later, possibly `/v1/embeddings` for archetype-memory retrieval — same server, zero extra processes. The Anthropic endpoint lets us point Claude Code at the box directly for side-by-side testing before soma exists.

## Capabilities we leverage

- `vllm-mlx serve <model> --port 8000 --continuous-batching`
- Prefix cache (trie-based, cross-request) — design shared prefixes into every LOCAL prompt template
- Dual API; tool calling with 19 parsers (verify which parser handles Qwen3-Coder and whether it needs a flag)
- `vllm-mlx bench-serve --url … --concurrency N --prompts … --output results.csv` — S7 uses this instead of hand-rolled load scripts
- Version pin: **0.4.1** (young project; upgrade deliberately, never implicitly)

## Capabilities we deliberately skip (for now)

- `[audio]` extra — no use case
- `--ssd-cache-dir` (SSD-tiered KV) — 96 GB unified memory is ample until we run long-context agents locally, which the tiering policy says we don't
- `--reasoning-parser qwen3` — Coder-Instruct is not a reasoning model; flag matters only if we later serve a thinking Qwen
- `/v1/rerank`, `/v1/responses` — revisit when memory retrieval needs a reranker

## Gotchas observed

- Decode speed decays hard with context length on Apple Silicon (the reference doc saw ~74 tok/s at 1K ctx → ~13 tok/s at 64K on a lesser chip). The LOCAL tier gets short-context mechanical work *by design*; S7 records our actual curve.
- Quantized models fail at tool-call *formatting* before they fail at reasoning — hence S1 before anything depends on this server.
- Apple Silicon only; Python ≥ 3.10 (machine's system Python is 3.9 — we run a uv-managed 3.12 venv).
- First load pulls ~17 GB into unified memory from SSD; expect tens of seconds before the first token after a cold start.

## Assumptions to verify

- **S1**: clean tool-call JSON over 10+ turns (spike: `spikes/s1_toolcall_soak.py`) — results below
- **S7**: usable aggregate tok/s under 4+ concurrent streams (`bench-serve`) — results below
- Prefix cache measurably cuts TTFT for shared-prefix prompts (micro-experiment, candidate EXP)
- OpenHands `LLM(base_url=…)` speaks to it cleanly (lands in P2)

## Spike results

*(to be filled when the model download completes and the server is up)*

- S1 soak: —
- S7 throughput: —

## Links

[repo](https://github.com/waybarrios/vllm-mlx) · [docs](https://vllm-mlx.is-a.dev/) · [PyPI](https://pypi.org/project/vllm-mlx/) · [model card](https://huggingface.co/mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit)
