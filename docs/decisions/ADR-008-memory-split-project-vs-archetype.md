# ADR-008 — Memory split: SDK MEMORY.md for project facts, soma for archetype memory

*Date: 2026-08-29 · Status: accepted*

## Context

P9 planned soma memory to cover both durable project facts and archetype memory. The SDK ships persistent memory (`AgentContext(load_memory=True)`): two-tier MEMORY.md indexes (user tier `~/.openhands/memory/`, project tier `<workspace>/.openhands/memory/`), maintained by the agent itself, injected at session start under a ~6K-character budget, and deliberately wrapped as `<UNTRUSTED_CONTENT>` because memory files are a prompt-injection vector.

## Decision

Division of labor, per Kushal: **the SDK's MEMORY.md owns user and project facts; soma memory is scoped purely to archetype memory** — episodic, semantic, procedural, and temporal records attached to agent *types* across runs. Theirs remembers the project; ours remembers the species.

Two adopted disciplines:

1. **Copy their untrusted-content wrapper** for every soma memory injection. Our archetype memories are machine-written and web-tainted content can reach them; they get the same quarantine framing.
2. **Single-writer rule for MEMORY.md**: in a colony, only the orchestrator's main-loop cell maintains the project MEMORY.md. Worker cells load it read-only. Eighty concurrent cells "curating" one index file is a merge war we decline to fight.

## Consequences

P9 scope shrinks to the genuinely novel part (the archetype pipeline: reflection over all of a cell's activity logs → episodes → consolidation → gated procedural promotion). The store decision (Mem0 vs custom, ADR-002) is unchanged and still waits on L9.

## Revisit when

Archetype memory turns out to need project-scoped shards, or MEMORY.md's size budget/curation model fights our orchestrator's usage.
