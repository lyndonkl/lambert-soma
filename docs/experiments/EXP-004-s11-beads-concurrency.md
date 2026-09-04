# EXP-004 — S11: embedded-mode Beads under concurrent writers

*Date: 2026-09-02 · Runs: spikes/s11_beads_concurrency.py, two temp boards · Status: decided*

## Hypothesis

bd 1.2.2's embedded Dolt (single-writer) either fails or corrupts when
5 cells write to ONE board concurrently, so the harness must serialize
board writes (or run `dolt sql-server`).

## Variable

Coordination only: 5 processes hammering create → claim → close with no
coordination, vs the same ops serialized through one lock.

## Metric

Failed operations, board consistency (closed count == cycles), and
latency (p50 / max) over 40 cycles = 120 write operations per arm.

## Setup

Fresh `bd init` per arm in a temp dir (never the project board);
`multiprocessing.Pool(5)`; each op is a real `bd ... --json`
subprocess; consistency read back with `bd list --status closed`.

## Result

| arm | ok | fail | closed on board | wall | p50 | max |
|---|---|---|---|---|---|---|
| concurrent (no lock) | 40 | 0 | 40 | 52.7s | 0.57s | **25.1s** |
| serialized (one lock) | 40 | 0 | 40 | 64.2s | 0.51s | 0.81s |

Embedded Dolt is **correct** under contention — zero failures, no lost
or doubled beads; it queues writers internally. The cost is tail
latency: one op stalled 25 seconds behind the lock, versus a 0.8s worst
case when the harness serializes. Throughput was similar either way.

Deviations from the bd docs, probed and relied upon in `soma/beads.py`:

- `--json` is not one envelope: create/comment return an object with
  `schema_version`; update/close/ready return bare arrays; errors are
  `{"error": ..., "schema_version": 1}` with exit 1.
- There is no `bd events` CLI and `events-journal` is not a recognized
  config key. The journal in 1.2.2 IS event beads (`--type=event`,
  `--event-payload`), listed with `bd list --type event`; `set-state`
  creates them too. Cells emit one on claim and one on close.
- `bd init` works without a git repo (~2.8s); reads ~0.2s, writes ~0.5s.

## Decision

**Per-cell boards, no shared writers at the cell level.** `bd init` in
each cell's bundle makes contention structurally impossible and keeps
the cell's board scope airtight (T3). When a shared team board arrives
(rung 2), serialize writes through the harness — correctness is already
guaranteed by Dolt, but bounded latency is not, and a 25s stall inside
a cell's step is a stuck-detector false positive waiting to happen.
`dolt sql-server` stays the fallback if the harness lock becomes the
bottleneck; measure first.
