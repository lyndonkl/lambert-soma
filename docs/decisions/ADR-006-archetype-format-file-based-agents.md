# ADR-006 — Archetype format: adopt the SDK's file-based agents

*Date: 2026-08-29 · Status: accepted*

## Context

We planned a soma-specific archetype format (markdown + custom `tier:` frontmatter) with our own loader and factory. The L2 guides review revealed the SDK's file-based agents: `.agents/agents/*.md` with `name`, `description`, `tools`, `model` (inherit or a named LLM profile), `skills`, `hooks`, `mcp_servers`, and per-agent `permission_mode`. They auto-register, follow documented priority rules, bundle into plugins, and the plugin structure is Claude Code compatible.

## Options

1. Keep our format, write a converter. Two formats to maintain; zero ecosystem benefit.
2. **Adopt the SDK format and extend it with our conventions (chosen).**
3. Fork the SDK loader. Upgrade-path suicide.

## Decision

The archetype IS a file-based agent definition. Our extensions ride inside the format:

- Tier binding: `model: <profile-name>` against LOCAL/WORKER/LEAD profiles in the SDK profile store (`profile_store_dir` points at soma's profiles).
- Per-archetype confirmation posture: the native `permission_mode` field.
- Soma-only concepts that the format cannot express (WAL subscriptions, memory namespace overrides) live under `metadata:` keys prefixed `soma_`, so files stay loadable by stock SDK tooling.
- A soma validation pass runs over loaded definitions (G9: third-party archetypes are data, and data gets validated).

## Consequences

Easier: G9's plugin surface is now an existing, documented standard; Kushal's Claude Code library ports with minimal translation; loader/factory code we planned is mostly deleted. Harder: our conventions must never collide with SDK frontmatter keys, and SDK format evolution can move under us — pin versions, validate on load.

## Revisit when

The format cannot express an org-critical concept cleanly, or the `metadata: soma_*` convention grows past a handful of keys.
