# Archetypes — bring your own roles

soma ships no roles. An archetype is yours: a Markdown file in the
SDK's file-agent format (ADR-006), validated by `soma archetypes list`.

## Where they live

| Location | Level | Wins on name clash |
|---|---|---|
| `<project>/.agents/agents/*.md` | project | yes |
| `~/.agents/agents/*.md` | user library | no |

Keep your personal library at `~/.agents/agents/` and it is available
in every project; drop a same-named file into a project to override it
there (the shadow shows up as a note in validation).

## Format

```markdown
---
name: scout                # defaults to the file stem
description: One line on what this role is for.
model: local               # a tier name from soma.toml (fit-first: name the seat)
tools:
  - terminal
skills: []                 # optional, resolved by name at mint time
soma_version: 1            # reserved soma_* namespace, top level only
---
The body is the archetype core — layer 1 of the prompt (Cell
Protocol B3). What goes here is your craft: write it for the model
the tier points at.
```

Notes:

- `model:` names a **tier**, never a raw model slug — repoint the tier
  in `soma.toml` and every archetype bound to it follows.
- `soma_*` keys sit at the frontmatter **top level** (the SDK collects
  unknown top-level keys into the definition's metadata). Nesting them
  under a `metadata:` block is a validation error.
- Unknown tools, unknown tiers, duplicate names, and unknown `soma_*`
  keys all fail validation with the fix named.

## Check yours

```bash
soma archetypes list
```

Lists every effective archetype with level, tier, and tools, then runs
the pre-flight checks — the same failures the factory would otherwise
raise the moment a cell is minted.
