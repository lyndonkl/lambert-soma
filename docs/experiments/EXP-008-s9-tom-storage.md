# EXP-008 — S9: what the SDK's Tom tools actually store

*Date: 2026-09-08 · Runs: spike `spikes/s9_tom_storage.py` (untracked), results in `spikes/s9_results.json` · Status: decided (recommendation; ADR-007 amendment PROPOSED)*

## Hypothesis

The Tom tools' persisted user model (tom-swe 1.0.3 via
`openhands.tools.tom_consult`) is rich enough to be our
InterlocutorModel substrate (PLAN Appendix D): schema covers goals,
constraints, knows, gaps, prefers, open threads, register; it updates
per turn; cost per update is tolerable on the LOCAL tier.

## Variable

None — a probe. One synthetic 14-message session (7 user turns
scripted to reveal a goal, a hard constraint, a misconception, two
preferences, an open thread, and a blunt register), written in the
SDK's own event format, then SleeptimeCompute + one Consult.

## Metric

Field-by-field coverage of Appendix D; write cadence; LLM calls,
tokens, latency per operation; whether the LOCAL model survives the
tools' structured-output prompts.

## Setup

LOCAL tier only (cloud key rejected): vllm-mlx, Qwen3-Coder-30B-4bit.
`TomConsultExecutor(file_store=LocalFileStore(<scratch>), enable_rag=False,
llm_model="openai/<local id>", api_base=<local>)`. Note: the SDK tool's
`create()` hard-codes `~/.openhands` as the store root; redirecting
requires constructing the executor yourself. Every litellm call was
wrapped to record tokens and latency.

## Result

**Where and what it writes** (all under `<store root>/usermodeling/`):

| file | content | size |
|---|---|---|
| `cleaned_sessions/<sid>.json` | the messages verbatim + an `is_important` flag per message | 2.9 KB |
| `session_models/<sid>.json` | `SessionAnalysis`: `intent` (9-way enum), `user_modeling_summary`, `session_tldr`, `per_message_analysis[{message_content, emotions, preference}]` | 2.4 KB |
| `overall_user_model.json` | `UserAnalysis`: `user_profile{user_id, overall_description[], preference_summary[]}` + `session_summaries[{session_id, session_tldr}]` + `last_updated` | 1.8 KB |
| `processed_sessions_timestamps.json` | which sessions were indexed, event counts | 0.1 KB |

**Cadence.** Writes happen **only when SleeptimeCompute runs** (an
explicit tool call or a harness call at session end). Consult reads
the model and writes nothing. There is **no per-turn update path** —
re-running sleeptime re-analyzes whole sessions.

**Cost on LOCAL** (14-message session):

| op | LLM calls | prompt / completion tokens | wall |
|---|---|---|---|
| SleeptimeCompute | 2 (`SessionAnalysisForLLM`, `UserProfile`) | 3,156 / 797 | 20.7 s |
| Consult | 1 (`ActionResponse`, model + history in prompt) | 6,979 / 306 | 19.2 s |

The 30B local model handled every structured-output call (pydantic
`response_format` through litellm) without a fallback — no "too weak"
finding. Consult's 7K-token prompt makes it an occasional tool, not a
per-turn one, on any paid tier.

**Appendix D coverage, field by field:**

| InterlocutorModel field | in the Tom store? | evidence from the run |
|---|---|---|
| `goals` | **partial** | only `intent` (enum: `code_explanation`) + prose summaries; the stated "$200/month" goal appears nowhere |
| `constraints` | **partial, mislabeled** | "no Anthropic/OpenAI" and "M3 Max local" landed in `preference_summary` as preferences |
| `knows` | **missing** | no field, nothing captured |
| `gaps` (misconceptions) | **missing** | the SessionStart misconception became `emotions: confused` + "wants clear explanation" — the content of the misconception is lost |
| `prefers` | **present, strong** | `preference_summary` captured plain-language, explain-before-changing, research-backed, action-explicit — all correct |
| `open_threads` | **missing** | the unanswered turn-cap question and the pending PR walkthrough are not recorded |
| `register` | **partial** | per-message `emotions` enum (neutral/confused/focused/explorative) + prose "direct communication"; no summarized register |
| `updated_at` | **present** | `last_updated` on session and overall models |

Extras they have that Appendix D lacks: `is_important` per message,
per-message emotion, a session tl;dr list. Quirk: with the default
empty `user_id`, the profile's `user_id` came back as the session id
(the LLM filled it) — harmless, but the field is not trustworthy.

**Surprises.** (1) 4 of 8 fields are simply absent, and two more are
flattened into "preferences" — the store is a *preference* model, not
a mental-state model. (2) No per-turn path exists at all; per-turn
updates would be ours to build regardless. (3) The store root cannot
be redirected through the SDK tool's public `create()` — any soma
wrapper must build the executor directly (consistent with ADR-007's
"wrap behind a soma interface").

## Decision

**Recommend: build beside, not inside.** Keep the Tom store as the
substrate for what it is good at — `prefers` (strong), session tl;drs,
the emotion signal for `register` — and call SleeptimeCompute as the
end-of-session consolidation job (it already paces like our "sleep").
Add a soma-owned `interlocutor.json` in the same store root for the
fields Tom lacks (`goals`, `constraints`, `knows`, `gaps`,
`open_threads`, summarized `register`), updated per turn by the LOCAL
extraction pass Appendix D always planned. Do **not** mutate their
schema: their pipeline regenerates the profile files, so extensions
inside them would be overwritten. This is a refinement of ADR-007,
not a reversal — proposed as an amendment for Kushal's decision; the
alternative (own store, theirs as reference) stays viable and differs
mainly in whether we keep calling their Consult.
