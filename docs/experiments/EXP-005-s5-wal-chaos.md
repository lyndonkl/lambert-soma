# EXP-005 — S5: SQLite-in-WAL-mode as the soma WAL under interleaved writers

*Date: 2026-09-03 · Runs: `tests/test_wal.py::test_S5_chaos_interleaved_writers_lose_nothing`, live run 20260903-022159-a7c8a7 · Status: decided*

## Hypothesis

One SQLite file per run, opened in WAL mode with a busy-timeout, holds
up as the Kind-2 log under many concurrent writers. No event is lost,
none is doubled, and per-channel id order equals insertion order. The
per-cell publish rate limit throttles a gossip storm with an actionable
message instead of an exception.

## Variable

Concurrency: 8 writer threads, each with its own connection,
interleaving 1,250 publishes across 4 channels (10,000 events total),
versus the single-writer baseline of ordinary runs.

## Metric

Exactly 10,000 rows; every (writer, sequence) pair present exactly
once; per-channel ids strictly ascending and unique; zero writer
exceptions. Gossip storm: at a budget of 5/minute, publishes 6–8 are
refused with the limit named, and nothing past the budget lands.

## Setup

`src/soma/wal.py`: `PRAGMA journal_mode=WAL`, `synchronous=NORMAL`,
`timeout=5s` busy retry, one transaction per publish. Ids are ULIDs
(48-bit ms + 80-bit random) made monotonic within the process under a
lock. Rate limit is counted from the DB (`author` rows in the last 60s)
so it holds across tool instances and processes. Apple M3 Max, local
disk.

## Result

- **S5 chaos: 10,000 events in 0.29 s ≈ 34,800 events/s, 0 errors.**
  Count exact, no duplicates, every (writer, n) pair seen once, all
  four channels strictly ordered by id.
- **Gossip storm:** 8 publishes at budget 5 → `[ok ×5, refused ×3]`,
  refusal text names the limit and says to batch; channel count stays
  at 5.
- **Live:** a real `soma run` bundle now carries `wal.db`; the cell's
  task log `cell:proto-…` has the briefing as event 1 (author
  `harness`, kind `briefing`) — B1 holds on disk, not only in tests.

Caveats worth carrying: monotonic ids are guaranteed within one
process; two processes writing in the same millisecond can interleave
within that millisecond (still unique, still time-ordered at ms
granularity). The chaos arm used threads; a multi-process arm belongs
with the scheduler (rung 2), where it becomes the real shape.

## Decision

**adopt** — SQLite in WAL mode is the Kind-2 substrate (ADR-001
recommendation confirmed; JSONL+flock fallback not needed). Carry the
multi-process arm into rung 2's scheduler tests, and revisit the
publish budget (30/min default) once real team traffic exists.
