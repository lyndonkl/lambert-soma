# Lambert-Soma

> **A body for the model. A world for the swarm.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-pre--alpha%20%C2%B7%20design%20phase-orange.svg)](PLAN.md)

Lambert-Soma is an open-source, **local + cloud hybrid harness** for running societies of AI agents. We are building it to replace a proprietary coding-agent subscription with something we own end to end. At its core is an **orchestrator**: it runs the main loop, works a goal solo when that's enough, and convenes an **organization** when it isn't — one team or many, flat or hierarchical, staffed by specialized subagents. Those agents plan on a shared task graph. They talk to each other through **shared write-ahead logs and typed events**. And their generic *types* (not instances) accumulate **episodic, semantic, procedural, and temporal memory** across every life they live.

**Status:** 🥚 pre-alpha, design-and-learning phase. The full end-to-end plan lives in [PLAN.md](PLAN.md). Reference hardware is an Apple M3 Max (96 GB unified memory). The local inference tier is **Apple Silicon only in v0** — it sits behind a generic local-provider interface, so other backends (CUDA vLLM, llama.cpp) can slot in later. Everywhere else, the harness runs cloud-only.

---

## Quickstart (pre-alpha)

Requires [uv](https://docs.astral.sh/uv/). Works on any OS; the local tier lights up only on Apple Silicon (see below).

```bash
git clone https://github.com/lyndonkl/lambert-soma && cd lambert-soma
uv sync --extra local-mlx    # on non-Apple hardware the extra is a quiet no-op
uv run soma doctor           # what can this box do?
uv run soma local up         # Apple Silicon: start the local model server
                             # (first run downloads ~17 GB into the HF cache)
```

`soma doctor` is the contract: it tells you which tiers your machine has — local + cloud, cloud-only, or local-only — and verifies the local server actually answers with a real completion. The serve flags baked into `soma local up` are load-bearing: without the right tool-call parser, a healthy model looks broken. Cross-platform stance: install never breaks anywhere; capability differs by machine, and doctor reports it (`docs/decisions/ADR-005`).

## Why "Lambert-Soma"?

Two books name this project: Siddhartha Mukherjee's *The Song of the Cell* and Greg Egan's *Permutation City*.

### Soma — the body that makes a genome alive

In cytology, the **soma** is the cell body: the membrane, the organelles, the cytoplasm, the signaling machinery. Deep inside it sits the nucleus, holding the genome. And the genome, for all its glory, is *not alive*. DNA in a jar does nothing. It becomes a life only when a soma surrounds it — ribosomes to express it, a membrane to bound it, mitochondria to power it, receptors to let it hear its neighbors.

An LLM's weights are a genome: an immense frozen text written by training, identical in every copy, inert in a file on disk. **Lambert-Soma is the soma** — everything the nucleus needs in order to become a cell, and everything a brain needs in order to have hands and memory:

| Biology | Lambert-Soma |
|---|---|
| DNA in the nucleus | frozen LLM weights behind an API (local or cloud) |
| Gene expression | prompts, skills, and tools — one genome, many phenotypes |
| Cell differentiation | the same weights expressed as dozens of distinct agent archetypes |
| Organelles | tools: shell, editor, browser, MCP servers |
| Cell membrane | sandboxed workspaces, with a security analyzer at the receptor |
| Metabolism | token budgets and tiered model routing (local / cheap / frontier) |
| Cell signaling | typed events on a shared write-ahead log |
| Pheromone trails (stigmergy) | the shared task graph — work state the whole colony can read |
| Mitosis | spawning subagents |
| Apoptosis | loop detection and programmed termination of stuck agents |
| Epigenetic memory | archetype memory: instances die, the *type* remembers |
| Cells → tissues → organs → organism | agents → teams → hierarchies → organization |

Two details of the metaphor are load-bearing, not decorative:

- **Differentiation is the whole trick.** A neuron and a hepatocyte carry identical DNA; what differs is which genes are expressed. Likewise every agent here runs the same weights — what makes one a security auditor and another a release manager is expression: system prompt, skills, tools, memory. The harness is, quite literally, the expression machinery. (In neuroscience, "soma" specifically means the body of a *neuron* — fitting, since what we are embodying is a brain.)
- **The Weismann barrier holds.** In biology, nothing the soma learns is written back into the germline. Lambert-Soma honors that: we never fine-tune. All learning is somatic — memories, skills, expression. The genome stays frozen; the cell gets wiser.

### Lambert — the world where seeded life outgrows its designers

In *Permutation City*, **Planet Lambert** is a world inside the Autoverse: a simulated chemistry seeded with a single hand-designed bacterium, *Autobacterium lamberti*, and then left to run. The seed does not stay a demo. It evolves into the Lambertians — swarm intelligences with societies, cooperation, and eventually a science of their own that no longer needs the hypothesis of their creators.

Lambert is our name for the **world half** of the project: the runtime the agent-cells live in. A place where agents are spawned, form colonies, divide labor, leave trails for each other, and where agent *types* evolve across generations of runs through accumulated memory — the designers seed it, but what the colony learns is its own.

Egan's dust theory holds that a mind is a pattern that can be assembled from scattered moments, indifferent to substrate. Lambert-Soma's agents live that way by construction: an agent *is* an append-only log of events. Any "current state" is just a view assembled from that log. Pause it, replay it, condense it, move it between the laptop on your desk and a datacenter GPU — the pattern is the identity, not the hardware. That is also why the harness is hybrid local + cloud from day one: substrate independence isn't a feature, it's the premise.

Together: **Soma gives the weights a body. Lambert gives the bodies a world.**

---

## What it will do

- **Orchestrator main loop** — receives a goal, decides: handle it solo, or convene an organization.
- **Organizational architectures** — single or multiple teams, with collaboration and hierarchy. The end user can supply a team design; if they don't, a **planner subagent** generates an organizational plan (including custom, inline-defined subagent archetypes), validated against a schema before anything spawns.
- **Communication fabric** — each agent keeps a private append-only event log; the colony shares a **write-ahead log** of typed events (messages, discoveries, artifacts, help requests) with per-agent cursors, plus a [Beads](https://github.com/steveyegge/beads) task graph for work state: what's ready, claimed, blocked, discovered.
- **Theory-of-mind conversational layer** — the conversational agent keeps an explicit model of its interlocutor: goals, knowledge, gaps, open threads. It delegates *within itself* to cognitive-style subagents — the analyst, the socratic questioner, the explainer, the critic, the synthesizer — and composes their outputs into the reply. Conversation as a society of minds.
- **Archetype memory** — generic agent types grow **episodic** (what happened), **semantic/long-term** (distilled lessons), **procedural** (learned heuristics promoted into skills), and **temporal/periodic** (time-indexed, decaying, cadence-aware) memory. Instances are mortal; the archetype remembers.
- **Tiered model routing** — LOCAL (Apple-Silicon inference via vllm-mlx: condensation, extraction, classification, loop checks) / WORKER (cheap cloud: bulk execution) / LEAD (frontier: orchestration and review), with per-agent cost attribution.
- **Sentinels** — rule-based *and* semantic loop detection, budget circuit breakers, and apoptosis: stuck agents are terminated and their post-mortem becomes an episode in archetype memory.
- **Sandboxing** — local workspace while you watch, container workspace when you walk away. One-line swap.
- **The lab bench** — every run is an experiment: structured telemetry, a run ledger, replayable event logs, shadow-mode rollouts for new subsystems, and a benchmark task suite. The harness measures itself so we know where it's weak.

## Architecture (target state)

```
                     ┌────────────────────────────────────────────┐
     user goal ────▶ │                ORCHESTRATOR                │
   (± org design)    │   main loop · solo ⇄ organization decision │
                     │        ┌────────────────────────┐          │
                     │        │ planner subagent        │          │
                     │        │ → OrgPlan (validated)   │          │
                     │        └────────────────────────┘          │
                     └──────────┬──────────────────┬──────────────┘
                                │ compiled into    │
                   ┌────────────▼─────────┐  ┌─────▼────────────────┐
                   │  TEAM "feature"      │  │  TEAM "quality"      │
                   │  lead ▸ workers (n)  │  │  reports_to: feature │
                   └───────┬──────────────┘  └─────┬────────────────┘
                           │                       │
        ┌──────────────────▼───────────────────────▼───────────────┐
        │  COMMUNICATION FABRIC                                    │
        │  shared write-ahead log — typed events, cursors, inboxes │
        │  Beads task graph — ready / claim / close / discovered   │
        └──────────────────┬───────────────────────┬───────────────┘
                           │                       │
        ┌──────────────────▼──────────┐  ┌─────────▼───────────────┐
        │  ARCHETYPE MEMORY           │  │  SENTINELS              │
        │  episodic · semantic ·      │  │  loop detection (rules  │
        │  procedural · temporal      │  │  + semantic) · budgets  │
        │  consolidation ("sleep")    │  │  · apoptosis            │
        └─────────────────────────────┘  └─────────────────────────┘
                           │  every LLM call routed by tier
        ┌──────────────────▼────────────────────────────────────────┐
        │  LOCAL (vllm-mlx on M3 Max) │ WORKER (cheap) │ LEAD (top) │
        └───────────────────────────────────────────────────────────┘
```

## Stack

| Layer | Choice | Why |
|---|---|---|
| Agent harness | [OpenHands SDK](https://docs.openhands.dev/sdk/arch/sdk) (V1) | Event-sourced agent loop, tools, workspaces, condenser, delegation — MIT licensed |
| Local inference | [vllm-mlx](https://github.com/waybarrios/vllm-mlx) | Continuous batching, prefix caching, paged KV cache on Apple Silicon; OpenAI + Anthropic endpoints |
| Provider routing | LiteLLM (inside the SDK's `LLM`) + OpenRouter | One interface, 100+ providers, per-`usage_id` cost accounting |
| Work state | [Beads](https://github.com/steveyegge/beads) (`bd`) | Dependency-aware task graph shared by all agents |
| Fact memory | [Mem0](https://github.com/mem0ai/mem0) or custom store | Library, not runtime — OpenHands keeps the loop |
| Inter-agent comms | SQLite in WAL mode (yes, literally a write-ahead log) | Typed events, concurrent readers, per-agent cursors, replayable |
| Isolation | Local ↔ Docker workspaces | Same code path, one-line swap |

## Roadmap (condensed — see [PLAN.md](PLAN.md))

1. **Substrate** — local model server up, tool calling verified, baseline costs measured
2. **Spine** — single agent on the SDK, condenser on the local tier, per-agent cost metrics
3. **Differentiation** — file-based archetypes, tier routing, the agent factory
4. **Teams** — delegation, Beads integration, first lead-plus-workers team
5. **Signaling** — the shared WAL, typed events, cursor-based inboxes
6. **Organizations** — OrgPlan schema, planner subagent, multi-team hierarchical runs
7. **Sentinels** — semantic loop detection, budgets, apoptosis
8. **Theory of mind** — interlocutor model + cognitive-style composition
9. **Memory** — archetype memory: episodes, consolidation, procedural promotion
10. **Hardening** — container-by-default unattended runs, skill audit, scale-out

Throughout: telemetry first — every subsystem ships in shadow mode, measured before it's armed.

## Reading

- Siddhartha Mukherjee, *The Song of the Cell* — where "soma" comes from
- Greg Egan, *Permutation City* — where "Lambert" comes from
- [OpenHands SDK paper](https://arxiv.org/abs/2511.03690) — the harness we build on

## License

[MIT](LICENSE). Built on the shoulders of MIT-licensed giants; it would be rude to be less open.
