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
