# EXP-007 — S12: Mem0 OSS as the archetype memory store?

*Date: 2026-09-08 · Runs: spike scripts `spikes/s12_*.py` (untracked) over 11 episodes distilled from real run bundles · Status: decided-as-recommendation (human gate: ADR-002)*

## Hypothesis

Mem0 OSS, configured entirely on the local tier (vllm-mlx Qwen3-Coder as
LLM, a served embedding model), stores archetype-scoped episodes and
recalls them well enough for birth injection at acceptable latency —
better than a small custom store (plan B) would.

## Variable

Store implementation: **Mem0 OSS 2.0.20** (embedded Qdrant on disk) vs
**plan B** (SQLite + served embeddings + cosine, ~47 lines of store
code). Embedder as a secondary variable: `embeddinggemma-300m-6bit`
(768-d) vs `all-MiniLM-L6-v2-4bit` (384-d), both served by vllm-mlx.

## Metric

Over 10 questions a cell would ask at birth ("how do I write
greeting.txt so it lands in the workspace?", "what goes wrong when
condensation is too aggressive?"), against 11 episodes with known
relevance: **top-1 hit rate** and precision@3 (p@3 is capped by
single-relevant queries — 6 of 10 have one relevant episode, so 0.33 is
perfect for them). Plus add/search latency, store size, and the OSS
constraints from the mental model, checked live.

## Setup

- Local only — the cloud key had expired (401), which turned out to
  matter (see surprises). LLM: `openai` provider → vllm-mlx
  `/v1/chat/completions`. Embedder: `openai` provider → vllm-mlx
  `/v1/embeddings` (a request-time-loadable allowlist of 7 MLX embedding
  models exists; no sentence-transformers download needed).
- Vector store: Mem0's default embedded Qdrant, `on_disk` in a scratch
  dir; history in SQLite there too. Nothing touched `~/.soma`.
- Corpus: 11 episodes hand-distilled from real bundles (run ids in the
  script): the local goldfish loop, the clean haiku, `/tmp` path
  wandering, the shouty/quiet role runs, the cloud 402 crash, the cloud
  goldfish loop, the bd-refusal stuck run, the remember run, the
  Stop-hook E2E. `agent_id` = archetype (`proto`/`shouty`/`quiet`);
  metadata `kind/tier/status`; `run_id` as Mem0's identity field.

## Result

| arm | init | add (verbatim) | search | top-1 | p@3 | store |
|---|---|---|---|---|---|---|
| Mem0 + gemma 768-d | 0.69 s | 0.04 s | 0.026 s | **9/10** | 0.47 | 261 KB |
| Mem0 + MiniLM 384-d | 0.68 s | 0.07 s | 0.016 s | **9/10** | 0.47 | 189 KB |
| plan B + gemma 768-d | — | 0.16 s | 0.009 s | **9/10** | 0.47 | 220 KB |

Recall is **identical** between Mem0 and plan B with the same embedder —
same rankings on every query — which is what it should be: both are
cosine over the same vectors. The one top-1 miss (q10, "when should I
stop verifying and call finish?") ranked the Stop-hook episode above the
clean-haiku one; both embedders made the same call. Recall quality here
is the embedder's, not the store's.

**Served embeddings on vllm-mlx** (new fact): `embeddinggemma-300m-6bit`
768-d loads in 19.5 s once, then 0.08 s per 8 texts; `all-MiniLM-L6-v2-4bit`
384-d 3.3 s then 0.20 s; `multilingual-e5-small` 384-d works;
`bge-large-en-v1.5-4bit` returns HTTP 500. The local tier can embed for
free at ~100 texts/s.

**Mem0 `infer=True`** (LLM fact extraction) works on the local Qwen:
2.5–15.8 s per episode, 1–8 facts each — but phrased as *"User created
haiku.txt…"*: Mem0's default extraction prompt assumes a human user.
A `custom_instructions` knob exists; untested. `memory_type` accepts only
`procedural_memory` (LLM-summarized); "episodic"/"semantic" are ours to
carry in metadata, as the mental model said.

**Mem0 2.0.20 constraints, checked live** (the docs lag):

- `metadata["run_id"]` is silently dropped — `run_id` is an identity
  field and must be a top-level argument.
- `search()` no longer accepts `agent_id=`; it requires `filters=` with
  at least one of `user_id/agent_id/run_id`, and an `OR` across
  `agent_id`s is rejected. Cross-archetype recall = one search per
  archetype. (For birth injection this is fine: a cell reads its own
  archetype's drawer, ADR-008.)
- `expiration_date` works OSS: hidden by default, `show_expired=True`
  reveals. `agent_id` scoping is exact (shouty query → only E4).

**Surprises:**

1. Mem0's `openai` LLM provider **auto-routes to OpenRouter whenever
   `OPENROUTER_API_KEY` is in the environment**, ignoring
   `openai_base_url`. Our expired key exposed it (401 "API key
   expired" from a supposedly local call). Mitigation: unset the var for
   the process or use Mem0's `vllm` provider.
2. **Telemetry is on by default** (PostHog client warnings); `MEM0_TELEMETRY=false`
   is required for a local-first tool.
3. Footprint: 8 direct requirements — `httpx, openai, posthog, protobuf,
   pydantic, pytz, qdrant-client, sqlalchemy` — an embedded vector DB and
   an ORM for a store our cell level drives with two calls.
4. Plan B's brute-force cosine is pure Python here (9 ms at 12
   vectors); it needs numpy (already installed) past a few hundred
   episodes — a two-line change, not a design change.

## Decision

**Recommendation, for the ADR-002 gate: plan B for v0**, behind the
`MemoryStore` interface PR-12 already fixed, keeping Mem0 as the
upgrade path. Reasoning: recall is the embedder's and is identical;
what Mem0 adds — LLM fact extraction, add/update/delete arbitration, a
history table — is machinery the Rung-4 *sleep job* may want, but the
reflection path rows 30/31 planned writes verbatim episodes
(`infer=False`) where Mem0 is a thin wrapper. Against that: eight
dependencies including telemetry, an API whose identity/filter
semantics shifted between docs and 2.0.20, a silent OpenRouter
rerouting, and no cross-archetype query. The served embedder is the
real win of this spike and both plans share it. Kushal decides in
ADR-002.
