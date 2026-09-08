# ADR-002 — The archetype memory store: Mem0 OSS or a small custom store

*Date: 2026-09-08 · Status: **proposed** (human gate — Kushal decides; evidence in [EXP-007](../experiments/EXP-007-s12-mem0-eval.md))*

## Context

ADR-008 split memory: the SDK's `MEMORY.md` holds project and user
facts; soma holds **archetype memory** only — episodes written by a
reflection rider at a cell's death, semantic cards promoted from them
by a sleep job, procedural promotions behind a human gate, and top-k
"prior experience" injected at birth (Rung 4, rows 30/31, PLAN §P9).
PR-12 fixed the cell-level interface: `MemoryStore.mark` / `markers`.
Rung 4 needs the store behind it. Kill-list S12 asked whether Mem0 OSS
is that store or whether we write ~300 lines ourselves; the spike ran
both on the local tier against real episodes.

## Options

**A — Mem0 OSS 2.0.x** (embedded Qdrant on disk, `agent_id` = archetype,
served embedder). *Works today*: verbatim episodes, expiration, exact
per-archetype scoping, and LLM fact extraction on the local model. *Downsides,
measured*: 8 direct dependencies (an embedded vector DB, an ORM, and
PostHog telemetry on by default); its OpenAI provider silently reroutes
to OpenRouter when that env var exists; identity/filter semantics
changed between its docs and 2.0.20 (`run_id` is not metadata; no
`agent_id` in `search()`; no OR across archetypes); extraction prompts
assume a human "User". Its real value — add/update/delete arbitration
and LLM extraction — sits on paths our v0 design doesn't take.

**B — Custom store**: SQLite + the same served embedder + cosine (numpy),
one table per the interface, ~47 lines of core in the spike, ~300 with
expiry, caps, provenance, and tests. *Same recall as A* (identical
rankings — the embedder decides), 9 ms searches, no new dependencies,
no telemetry, fully under the layer doctrine. *Downside*: we own
consolidation ourselves when the sleep job arrives, and we own the
index once a drawer holds tens of thousands of episodes.

**C — Mem0 Platform** (hosted): graph, temporal decay, "Dream" — the
features that made Mem0 attractive on paper. *Rejected*: memories leave
the machine; incompatible with a local-first harness and the cost
ledger.

## Decision (proposed)

Adopt **B** as the v0 `MemoryStore` implementation, shaped so that A
remains a drop-in: the same `agent_id`-per-archetype namespace, metadata
`kind ∈ {episodic, semantic, procedural}`, `run_id` provenance,
`expiration_date`, and top-k search scoped to one archetype. The served
embedder (`embeddinggemma-300m-6bit` via vllm-mlx `/v1/embeddings`, 768-d)
is the embedding path for either option — the spike's most useful
finding. Reflection writes verbatim episodes (Mem0's `infer=False`
equivalent); consolidation is a soma LLM pass on the local tier,
designed when the sleep job is built. If that job wants Mem0's
arbitration machinery, A slots in behind the same interface.

## Consequences

Easier: no new dependencies at Rung 4, no telemetry to disable, one
SQLite file per archetype drawer under `~/.soma/`, recall identical to
Mem0's for the same embedder, and the whole store reads in a sitting.
Harder: dedup and update logic is ours; past a few thousand episodes
per archetype the cosine scan moves from numpy to an index (sqlite-vec
or a small HNSW) — a bounded, later change. Must do now: nothing; the
decision gates row 30. Must do if reversed: write the Mem0 adapter
(≈ the spike script), pin `MEM0_TELEMETRY=false`, use the `vllm`
provider, and search per archetype.

## Revisit when

The sleep job's consolidation needs LLM-mediated add/update/delete that
we would otherwise rebuild; a drawer exceeds ~5,000 episodes and search
latency crosses 100 ms; or Mem0 OSS ships cross-archetype filters and
opt-in telemetry — then rerun EXP-007 with A as the default.
