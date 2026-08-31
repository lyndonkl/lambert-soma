"""Telemetry ledger v0 (PR-03).

engine produces bundles -> ledger distills them into durable rows ->
`soma report costs` renders answers. Layer doctrine (ADR-010): the
cell never knows this exists. Rows are written by the harness AFTER a
run, from the bundle the cell left behind; aggregation only happens at
read time, over per-run, per-usage_id atoms.

DB lives at ~/.soma/telemetry.db by default ([soma] telemetry_db
overrides). Recording is best-effort: a ledger hiccup must never turn
a finished run into a failed one.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from soma.config import SomaConfig

MONTHLY_REFERENCE_USD = 200.0  # the Anthropic-Max comparison line (PLAN §2)

_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    conversation_id TEXT,
    task            TEXT,
    tier            TEXT,
    workspace       TEXT,
    status          TEXT,
    config_hash     TEXT,
    persistence_dir TEXT,
    started_at      TEXT,
    finished_at     TEXT,
    total_cost      REAL
);
CREATE TABLE IF NOT EXISTS llm_calls (
    run_id             TEXT,
    usage_id           TEXT,
    model              TEXT,
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER,
    cache_read_tokens  INTEGER,
    cache_write_tokens INTEGER,
    calls              INTEGER,
    cost               REAL,
    PRIMARY KEY (run_id, usage_id)
);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_DDL)
    return conn


def utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def config_hash(agent_dump: dict) -> str:
    """12 hex chars over the canonical agent settings dump.

    Same config -> same hash, so ledger rows are comparable; any change
    to model, tools, condenser, or clamps changes the hash.
    """
    canonical = json.dumps(agent_dump, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def harvest_bundle(persistence_dir: Path) -> dict | None:
    """Read the one base_state.json a run bundle holds, or None."""
    candidates = sorted(persistence_dir.glob("*/base_state.json"))
    if not candidates:
        return None
    return json.loads(candidates[0].read_text())


def record_run(
    cfg: SomaConfig,
    run_id: str,
    task: str,
    tier: str,
    workspace: str,
    status: str,
    persistence_dir: Path,
    started_at: str,
    finished_at: str | None = None,
) -> bool:
    """Distill one run bundle into ledger rows. Best-effort by contract."""
    try:
        state = harvest_bundle(persistence_dir)
        conversation_id = state.get("id") if state else None
        cfg_hash = config_hash(state["agent"]) if state and "agent" in state else None
        metrics = (state or {}).get("stats", {}).get("usage_to_metrics", {})
        total_cost = 0.0
        call_rows = []
        for usage_id in sorted(metrics):
            m = metrics[usage_id]
            tok = m.get("accumulated_token_usage") or {}
            cost = float(m.get("accumulated_cost") or 0.0)
            total_cost += cost
            call_rows.append((
                run_id, usage_id, m.get("model_name"),
                int(tok.get("prompt_tokens") or 0),
                int(tok.get("completion_tokens") or 0),
                int(tok.get("cache_read_tokens") or 0),
                int(tok.get("cache_write_tokens") or 0),
                len(m.get("response_latencies") or []),
                cost,
            ))
        with _connect(cfg.telemetry_db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, conversation_id, task[:200], tier, workspace, status,
                 cfg_hash, str(persistence_dir), started_at,
                 finished_at or utcnow_iso(), total_cost),
            )
            conn.execute("DELETE FROM llm_calls WHERE run_id = ?", (run_id,))
            conn.executemany(
                "INSERT INTO llm_calls VALUES (?,?,?,?,?,?,?,?,?)", call_rows
            )
        return True
    except (sqlite3.Error, OSError, ValueError, KeyError):
        # ledger trouble must never fail the run that produced the data
        return False


def run_meta(cfg: SomaConfig, run_id: str) -> dict | None:
    """The ledger's memory of one run (tier, task, started_at) — used by
    resume to reconstruct definitions. None if unrecorded."""
    db_path = cfg.telemetry_db_path
    if not db_path.is_file():
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT task, tier, workspace, started_at FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    return {"task": row[0], "tier": row[1], "workspace": row[2], "started_at": row[3]}


def render_costs(cfg: SomaConfig, since: str | None = None) -> str:
    """The costs report. Deterministic ordering for golden tests."""
    db_path = cfg.telemetry_db_path
    if not db_path.is_file():
        return "ledger is empty — no runs recorded yet (run: soma run \"...\")"
    with _connect(db_path) as conn:
        where, args = ("WHERE started_at >= ?", [since]) if since else ("", [])
        runs = conn.execute(
            f"SELECT run_id, status, tier, total_cost FROM runs {where} "
            "ORDER BY run_id", args,
        ).fetchall()
        if not runs:
            return "no runs in the selected window"
        run_filter = f"WHERE run_id IN (SELECT run_id FROM runs {where})"
        brains = conn.execute(
            f"SELECT usage_id, SUM(prompt_tokens), SUM(completion_tokens), "
            f"SUM(calls), SUM(cost), COUNT(DISTINCT run_id) "
            f"FROM llm_calls {run_filter} GROUP BY usage_id ORDER BY usage_id",
            args,
        ).fetchall()
        month_start = utcnow_iso()[:8] + "01"
        mtd = conn.execute(
            "SELECT COALESCE(SUM(total_cost), 0) FROM runs WHERE started_at >= ?",
            (month_start,),
        ).fetchone()[0]
    lines = [f"{'RUN':<24} {'STATUS':<12} {'TIER':<10} {'COST':>9}"]
    for run_id, status, tier, cost in runs:
        lines.append(f"{run_id:<24} {status:<12} {tier or '-':<10} ${cost or 0:>8.4f}")
    lines.append("")
    lines.append("per-brain totals (usage_id):")
    for usage_id, p, c, calls, cost, nruns in brains:
        lines.append(
            f"  {usage_id:<12} {p or 0:>10,} in / {c or 0:>8,} out tok"
            f"  {calls or 0:>4} calls  ${cost or 0:>8.4f}  ({nruns} runs)"
        )
    lines.append("")
    lines.append(
        f"month-to-date: ${mtd:.4f} of ${MONTHLY_REFERENCE_USD:.2f} reference"
        " (Anthropic Max line, PLAN §2)"
    )
    return "\n".join(lines)
