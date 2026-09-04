"""Discipline hooks — Beads enforced through the SDK's own hook system (PR-09).

Cells rely on Beads, so the discipline is a hook on the cell's
Conversation, not prompt text. Three shell-command hooks, each
`python -m soma.cli hook <event> --bundle <dir>`, where <dir> is the
conversation dir (<run bundle>/<conversation id hex>) — the same key
the cell's bd tools use (PR-08), so hooks and tools see ONE board:

- SessionStart      -> `bd prime --hook-json` on the cell's board. The SDK
                       records the result but injects nothing at
                       SessionStart (EXP-006); the first UserPromptSubmit
                       carries the discipline instead.
- UserPromptSubmit  -> injects a board digest (open claims, ready beads)
                       as additionalContext on every user message: board
                       state at every turn (T1).
- Stop              -> exit 2 while any bead on the cell's board is still
                       in_progress; the SDK feeds stderr back to the agent
                       and keeps it running (N2). A cell finishes by
                       closing its bead first (N1).

SDK exit-code contract: 0 = ok (stdout JSON parsed for additionalContext),
2 = block, and 1 = NON-blocking error — a trap. These commands never
exit 1: a failed check fails closed (2) or is reported in the injected
context.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from soma.beads import BdRunner, board_dir_for

HOOK_EVENTS = ("session_start", "user_prompt_submit", "stop")
HOOK_TIMEOUT_S = 60
DISCIPLINE = (
    "Board discipline (Cell Protocol T1/N1/N2): claim a bead with bd_claim "
    "before working; when the work is verified, bd_close it with a reason, "
    "THEN finish. You cannot finish while your claimed bead is open."
)


def runner_for_bundle(bundle: Path | str) -> BdRunner:
    """The cell's own board, bootstrapped if a hook fires before the tools did."""
    runner = BdRunner(board_dir_for(bundle))
    runner.bootstrap()
    return runner


def open_claims(runner: BdRunner) -> list[dict]:
    result = runner.run("list", "--status=in_progress")
    if not result.ok:
        raise RuntimeError(result.error or "bd list failed")
    return list(result.data or [])


def board_digest(runner: BdRunner) -> str:
    claims = open_claims(runner)
    ready = runner.ready()
    lines = [DISCIPLINE, ""]
    if claims:
        lines.append("Your open claim(s): " + "; ".join(
            f"{b['id']} — {b.get('title', '')}" for b in claims))
    else:
        lines.append("No claimed bead — you are idle (T1).")
    items = list(ready.data or []) if ready.ok else []
    if items:
        lines.append("Ready on your board: " + "; ".join(
            f"{b['id']} — {b.get('title', '')}" for b in items[:5]))
    elif not claims:
        lines.append("Nothing ready on your board either.")
    return "\n".join(lines)


def _ok(context: str) -> tuple[int, str, str]:
    return 0, json.dumps({"additionalContext": context}), ""


def bd_prime(runner: BdRunner) -> dict:
    """`bd prime --hook-json` (its own flag, not the generic --json envelope)."""
    proc = subprocess.run(
        ["bd", "prime", "--hook-json"], cwd=runner.board_dir,
        capture_output=True, text=True, timeout=HOOK_TIMEOUT_S, check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(
            f"bd prime failed (exit {proc.returncode}): {proc.stderr.strip()[:200]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"bd prime returned non-JSON: {proc.stdout[:120]!r}") from exc


def hook_session_start(bundle: Path | str) -> tuple[int, str, str]:
    """`bd prime --hook-json` re-wrapped into the SDK's stdout shape."""
    try:
        data = bd_prime(runner_for_bundle(bundle))
    except RuntimeError as exc:
        return 2, "", f"[soma hook] SessionStart: {exc}"
    text = (data.get("hookSpecificOutput") or {}).get("additionalContext") or json.dumps(data)
    return _ok(text)


def hook_user_prompt_submit(bundle: Path | str) -> tuple[int, str, str]:
    """Board digest on every user message. Never blocks the message."""
    try:
        return _ok(board_digest(runner_for_bundle(bundle)))
    except RuntimeError as exc:
        return _ok(f"[soma hook] board unavailable — {exc}. You cannot claim or close "
                   "tasks; say so and stop.")


def hook_stop(bundle: Path | str) -> tuple[int, str, str]:
    """N2: refuse to finish while a claimed bead is open. Fails closed."""
    try:
        claims = open_claims(runner_for_bundle(bundle))
    except RuntimeError as exc:
        return 2, "", f"[soma hook] Stop refused: cannot verify your board ({exc})"
    if claims:
        ids = ", ".join(b["id"] for b in claims)
        return 2, "", (
            f"[soma hook] Stop refused: bead(s) {ids} still in_progress on your board. "
            "If the work is done and verified, bd_close each with a reason; if it "
            "cannot be completed, bd_note why, then bd_close it. Then finish (N1/N2)."
        )
    return 0, "", ""


_HANDLERS = {
    "session_start": hook_session_start,
    "user_prompt_submit": hook_user_prompt_submit,
    "stop": hook_stop,
}


def run_hook(event: str, bundle: Path | str) -> int:
    """CLI entry: print the hook's stdout/stderr, return its exit code (0 or 2)."""
    handler = _HANDLERS.get(event)
    if handler is None:
        print(f"[soma hook] unknown event '{event}' (known: {', '.join(HOOK_EVENTS)})",
              file=sys.stderr)
        return 2
    code, out, err = handler(bundle)
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    return code


def hook_command(event: str, bundle: Path | str) -> str:
    # absolute: the SDK runs hooks with cwd = the cell's WORKSPACE, not the repo
    return f'"{sys.executable}" -m soma.cli hook {event} --bundle "{Path(bundle).resolve()}"'


def soma_hook_config(bundle: Path | str):
    """The HookConfig every cell Conversation mounts."""
    from openhands.sdk.hooks import HookConfig, HookDefinition, HookMatcher

    def matcher(event: str) -> list:
        return [HookMatcher(hooks=[HookDefinition(
            command=hook_command(event, bundle), timeout=HOOK_TIMEOUT_S)])]

    return HookConfig(
        session_start=matcher("session_start"),
        user_prompt_submit=matcher("user_prompt_submit"),
        stop=matcher("stop"),
    )
