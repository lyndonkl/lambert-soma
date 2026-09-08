# ADR-007 — Theory-of-mind layer builds on the SDK's Tom tools

*Date: 2026-08-29 · Status: accepted*

## Context

P8 planned an InterlocutorModel built from scratch: a LOCAL extraction pass maintaining a structured model of the user, plus a cognitive-style ensemble. The SDK ships Tom tools based on the TOM-SWE paper (arXiv 2510.21903): `TomConsultTool` (personalized guidance for vague requests) and `SleeptimeComputeTool` (indexes conversation history into persistent user models under `~/.openhands/user_models/`). That is the user-modeling half of our layer, already built and research-backed.

## Options

1. Build fully independent; use theirs as reference only.
2. **Build our layer on top: their user-model architecture is the substrate; we extend it (chosen).**
3. Use theirs as-is. It has no style ensemble, no per-turn composition, no agent-to-agent ToM.

## Decision

The Tom tools' user model becomes the substrate for our InterlocutorModel. We extend their model architecture rather than inventing a parallel one. What remains ours, layered on top: the cognitive-style ensemble (analyst, socratic, explainer, critic, synthesizer), per-turn routing and single-voice composition, dialogue overlays, and agent-to-agent ToM built from WAL event streams. Their "sleeptime compute" pattern also aligns with — and will pace — our memory consolidation "sleep" job.

## Consequences

P8 shrinks and re-sequences: it now STARTS with a spike (kill-list S9) inspecting exactly what sleeptime-compute writes (`user_model.json` schema, processing cadence, cost) before we commit schema extensions. Risk: the tools are young — we wrap them behind a soma interface so the substrate is swappable, and pin versions.

## Revisit when

Their schema cannot hold our fields, the tools stagnate upstream, or the S9 spike shows the stored model is too shallow to extend.

## Amendment — PROPOSED (S9, 2026-09-08, EXP-008)

**Finding.** The Tom store (tom-swe 1.0.3 via `openhands.tools.tom_consult`) is a
*preference* model, not a mental-state model. Of Appendix D's eight fields it
holds `prefers` (strong) and `updated_at`; `goals`, `constraints`, `register` are
partial; `knows`, `gaps`, `open_threads` are absent. Writes happen only when
SleeptimeCompute runs (2 LLM calls, ~3.2K prompt tokens, ~21 s on LOCAL per
session); there is no per-turn update path. Consult reads only and costs ~7K
prompt tokens per call. The SDK tool's `create()` hard-codes `~/.openhands` as
the store root; a soma wrapper must construct the executor directly.

**Proposed refinement: build beside, not inside.**

- Substrate stays theirs for what it does well: the store root, `prefers`,
  session tl;drs, per-message emotion, and SleeptimeCompute as the
  end-of-session consolidation pass (it already paces like our "sleep" job).
- soma owns a sibling document in the same store root, `interlocutor.json`,
  carrying the missing fields — `goals`, `constraints`, `knows`, `gaps`,
  `open_threads`, a summarized `register` — updated per turn by the LOCAL
  extraction pass Appendix D planned. Their schema is never mutated: their
  pipeline regenerates the profile files, so in-place extensions would be lost.
- Their Consult remains available as an occasional tool (not per turn) behind
  the soma interface; the style ensemble, router, and composer stay ours.

**Alternative kept open:** own store entirely, theirs as reference. It differs
mainly in whether we keep calling their Consult and reusing their store root.

**Decision owner:** Kushal, at the PR-34 human gate.
