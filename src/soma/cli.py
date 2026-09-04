"""soma CLI — bootstrap subset.

The orchestrator commands land with the build phases (see PLAN.md and
docs/build-plan.md). This bootstrap ships the environment story:

    soma init        write soma.toml (if absent) + one LLM profile per tier
    soma doctor      what can this box do? (config, profiles, local server)
    soma local up    run the local inference server with the canonical flags
    soma run         run one task in a proto-cell (one Conversation, PR-02)
    soma resume      continue a dead-but-unfinished run (Cell Protocol R1/R2)
    soma archetypes  list + validate the available roles (PR-05, ADR-006)
    soma skills      list + audit skills before cells mount them (PR-07)
    soma report      read the telemetry ledger (costs per run / per brain, PR-03)
    soma hook        (internal) SDK hook entry — Beads discipline per cell (PR-09)

The canonical flags exist because S1 taught us that without the right
tool-call parser, a healthy model looks broken (calls arrive as text).
Doctor and `local up` encode that lesson so every install repeats it.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import sys
import time
import urllib.error
import urllib.request

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")  # before any lazy SDK import

CANONICAL_MODEL = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit"
DEFAULT_PORT = 8000
# S1 lesson: these flags are mandatory, not optional (docs/decisions/ADR-005).
SERVE_FLAGS = [
    "--continuous-batching",
    "--enable-auto-tool-choice",
    "--tool-call-parser", "qwen3_coder",
]

OK, BAD, SKIP = "  ✓", "  ✗", "  –"


def _apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def _local_extra_installed() -> bool:
    return importlib.util.find_spec("vllm_mlx") is not None


def _get(url: str, timeout: float = 5.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def _post(url: str, payload: dict, timeout: float = 60.0) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def soma_init(args: argparse.Namespace) -> int:
    from pathlib import Path

    from soma.config import CONFIG_FILENAME, STARTER_TOML, load_config
    from soma.profiles import bootstrap_profiles

    cfg, path = load_config()
    if path is None:
        Path(CONFIG_FILENAME).write_text(STARTER_TOML)
        print(f"{OK} wrote ./{CONFIG_FILENAME} (starter — edit the cloud models to taste)")
        cfg, path = load_config()
    else:
        print(f"{OK} using {path}")
    for line in bootstrap_profiles(cfg, force=args.force):
        mark = OK if not line.startswith("warning") else BAD
        print(f"{mark} {line}")
    print(f"profiles at {cfg.profile_store_path} — verify with: soma doctor")
    return 0


def _cloud_keys_present(cfg) -> bool:
    """Cloud readiness comes from keys baked into profiles, not the shell env."""
    from openhands.sdk import LLMProfileStore

    if not cfg.profile_store_path.is_dir():
        return False
    store = LLMProfileStore(cfg.profile_store_path)
    for name in cfg.tiers:
        try:
            llm = store.load(name)
        except Exception:  # noqa: BLE001, S112 — doctor must survive any bad profile file
            continue
        if llm.api_key is not None and llm.api_key.get_secret_value():
            return True
    return False


def doctor(args: argparse.Namespace) -> int:
    from soma.config import load_config
    from soma.profiles import check_profiles

    base = f"http://localhost:{args.port}/v1"
    local_ready = False

    print(f"soma doctor — {platform.platform()}")
    print(f"{OK} python {platform.python_version()}")

    cfg, cfg_path = load_config()
    print(f"{OK} config: {cfg_path}" if cfg_path else f"{SKIP} no soma.toml — using defaults (run: soma init)")
    for ok_flag, message in check_profiles(cfg):
        mark = OK if ok_flag else (SKIP if ok_flag is None else BAD)
        print(f"{mark} {message}")

    from soma.beads import check_bd  # ladder PR-08: cells need bd for board ops

    for ok_flag, message in check_bd():
        mark = OK if ok_flag else (SKIP if ok_flag is None else BAD)
        print(f"{mark} {message}")

    if _apple_silicon():
        print(f"{OK} apple silicon: local tier possible on this machine")
        if _local_extra_installed():
            print(f"{OK} local-mlx extra installed (vllm-mlx)")
        else:
            print(f"{BAD} local-mlx extra missing — run: uv sync --extra local-mlx")
    else:
        print(f"{SKIP} not apple silicon: local tier unavailable in v0 (ADR-005) — cloud-only mode")

    try:
        models = _get(f"{base}/models")
        model_id = models["data"][0]["id"]
        print(f"{OK} local server up on :{args.port} — {model_id}")
        t0 = time.monotonic()
        resp = _post(f"{base}/chat/completions", {
            "model": model_id, "temperature": 0, "max_tokens": 8,
            "messages": [{"role": "user", "content": "Reply with exactly: ok"}]})
        ms = (time.monotonic() - t0) * 1000
        content = (resp["choices"][0]["message"].get("content") or "").strip()
        if content:
            print(f"{OK} round-trip completion in {ms:.0f}ms ({content!r})")
            local_ready = True
        else:
            print(f"{BAD} server responded but generated nothing — check serve flags")
    except (urllib.error.URLError, OSError):
        hint = "soma local up" if _local_extra_installed() else "cloud-only mode"
        print(f"{SKIP} no local server on :{args.port} ({hint})")

    cloud_ready = _cloud_keys_present(cfg) or bool(os.environ.get("OPENROUTER_API_KEY"))
    mark = OK if cloud_ready else BAD
    print(f"{mark} cloud tiers {'have credentials (profiles)' if cloud_ready else 'have no key'}"
          f"{'' if cloud_ready else ' — export OPENROUTER_API_KEY, then: soma init --force'}")

    if local_ready and cloud_ready:
        print("verdict: all tiers available")
    elif cloud_ready:
        print("verdict: cloud-only — LOCAL work will fall through to WORKER (slower budget burn)")
    elif local_ready:
        print("verdict: local-only — no cloud tiers until OPENROUTER_API_KEY is set")
    else:
        print("verdict: no usable tier")
        return 1
    return 0


def soma_run(args: argparse.Namespace) -> int:
    from pathlib import Path

    from soma.config import load_config
    from soma.engine import run_task

    cfg, _ = load_config()
    try:
        result = run_task(
            args.task,
            cfg,
            tier=args.tier,
            archetype=args.archetype,
            workspace=Path(args.workspace).resolve(),
            max_iterations=args.max_iterations,
            condense_at=args.condense_at,
            visualize=not args.quiet,
        )
    except ValueError as exc:  # actionable config problems (missing tier, ...)
        print(f"{BAD} {exc}")
        return 2
    mark = OK if result.ok else BAD
    print(f"{mark} run {result.run_id}: {result.status}")
    if result.detail:
        print(f"  {result.detail}")
    print(f"  bundle: {result.persistence_dir}")
    return 0 if result.ok else 1


def soma_resume(args: argparse.Namespace) -> int:
    from soma.config import load_config
    from soma.engine import resume_run

    cfg, _ = load_config()
    try:
        result = resume_run(
            args.run_id,
            cfg,
            tier=args.tier,
            max_iterations=args.max_iterations,
            visualize=not args.quiet,
        )
    except ValueError as exc:
        print(f"{BAD} {exc}")
        return 2
    mark = OK if result.ok else BAD
    print(f"{mark} resumed {result.run_id}: {result.status}")
    if result.detail:
        print(f"  {result.detail}")
    print(f"  bundle: {result.persistence_dir}")
    return 0 if result.ok else 1


def skills_list(args: argparse.Namespace) -> int:
    from soma.skills import load_skills

    skills = load_skills()
    if not skills:
        print(f"{SKIP} no skills found — soma ships none (skills are yours).")
        print("  project: ./.agents/skills/   user library: ~/.agents/skills/")
        return 0
    for name in sorted(skills):
        s = skills[name]
        kind = "agentskills" if s.is_agentskills_format else (
            "always-on" if s.trigger is None else "triggered")
        print(f"  {name:<24} [{kind:<11}] {s.source or '?'}")
    return 0


def skills_audit(args: argparse.Namespace) -> int:
    from soma.skills import audit_skills

    failed = False
    for ok_flag, message in audit_skills():
        mark = OK if ok_flag else (SKIP if ok_flag is None else BAD)
        failed = failed or ok_flag is False
        print(f"{mark} {message}")
    print()
    print("review the – lines; ✗ lines block mounting. (human gate, build-plan PR-07)")
    return 1 if failed else 0


def archetypes_list(args: argparse.Namespace) -> int:
    from soma.archetypes import check_archetypes, load_archetypes
    from soma.config import load_config

    cfg, _ = load_config()
    defs = load_archetypes(cfg)
    if not defs:
        print(f"{SKIP} no archetypes found — soma ships none (roles are yours).")
        print("  add project roles at ./.agents/agents/<name>.md")
        print("  or a personal library at ~/.agents/agents/<name>.md")
        print("  format: docs/archetypes.md")
        return 0
    width = max(len(d.name) for d in defs)
    for d in sorted(defs, key=lambda d: d.name):
        tools = ",".join(d.tools) or "-"
        print(f"  {d.name:<{width}}  [{d.level:<7}]  tier={d.model:<10}  tools={tools}")
        print(f"  {'':<{width}}  {d.description}")
    print()
    failed = False
    for ok_flag, message in check_archetypes(cfg):
        mark = OK if ok_flag else (SKIP if ok_flag is None else BAD)
        failed = failed or ok_flag is False
        print(f"{mark} {message}")
    return 1 if failed else 0


def report_costs(args: argparse.Namespace) -> int:
    from soma.config import load_config
    from soma.telemetry import render_costs

    cfg, _ = load_config()
    print(f"ledger: {cfg.telemetry_db_path}")
    print(render_costs(cfg, since=args.since))
    return 0


def soma_hook(args: argparse.Namespace) -> int:
    """Entry point for the SDK hook subprocesses (PR-09). Exits 0 or 2, never 1."""
    from soma.hooks import run_hook

    return run_hook(args.event, args.bundle)


def local_up(args: argparse.Namespace) -> int:
    if not _apple_silicon():
        print("local tier is Apple Silicon only in v0 (ADR-005); this box runs cloud-only.")
        return 1
    if not _local_extra_installed():
        print("vllm-mlx is not installed — run: uv sync --extra local-mlx")
        return 1
    exe = shutil.which("vllm-mlx")
    if not exe:
        print("vllm-mlx CLI not on PATH — is the venv active? (try: uv run soma local up)")
        return 1
    cmd = [exe, "serve", args.model, "--port", str(args.port), *SERVE_FLAGS]
    print("exec:", " ".join(cmd))
    if args.print_only:
        return 0
    # Replace this process with the server: ctrl-c stops it, nothing to babysit.
    # First run downloads the model (~17 GB) into the HuggingFace cache.
    os.execv(exe, cmd)
    return 0  # unreachable


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="soma", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    ini = sub.add_parser("init", help="write soma.toml (if absent) and the tier profiles")
    ini.add_argument("--force", action="store_true",
                     help="overwrite existing profiles with config values")
    ini.set_defaults(fn=soma_init)

    run = sub.add_parser("run", help="run one task in a proto-cell (one Conversation)")
    run.add_argument("task", help="what the cell should do, in plain words")
    run.add_argument("--tier", default="worker",
                     help="tier profile for the agent LLM (default: worker)")
    run.add_argument("--as", dest="archetype", default=None, metavar="NAME",
                     help="run as this archetype (see: soma archetypes list)")
    run.add_argument("--workspace", default=".",
                     help="directory the cell works in (default: cwd)")
    run.add_argument("--max-iterations", type=int, default=100,
                     help="hard cap on agent steps (default: 100)")
    run.add_argument("--condense-at", type=int, default=None,
                     help="condense history once it exceeds N events (default: SDK 240)")
    run.add_argument("--quiet", action="store_true", help="no live event visualizer")
    run.set_defaults(fn=soma_run)

    sk = sub.add_parser("skills", help="list + audit available skills")
    sk_sub = sk.add_subparsers(dest="skills_command", required=True)
    sk_list = sk_sub.add_parser("list", help="every skill, its trigger kind and source")
    sk_list.set_defaults(fn=skills_list)
    sk_audit = sk_sub.add_parser("audit", help="security + hygiene review (the gate artifact)")
    sk_audit.set_defaults(fn=skills_audit)

    arch = sub.add_parser("archetypes", help="list + validate available roles")
    arch_sub = arch.add_subparsers(dest="archetypes_command", required=True)
    arch_list = arch_sub.add_parser("list", help="every archetype, its tier, and validation")
    arch_list.set_defaults(fn=archetypes_list)

    res = sub.add_parser("resume", help="continue a dead-but-unfinished run (R1/R2)")
    res.add_argument("run_id", help="the runs/<run_id> bundle to continue")
    res.add_argument("--tier", default=None,
                     help="override the tier (default: the ledger's memory of the run)")
    res.add_argument("--max-iterations", type=int, default=100)
    res.add_argument("--quiet", action="store_true")
    res.set_defaults(fn=soma_resume)

    rep = sub.add_parser("report", help="read the telemetry ledger")
    rep_sub = rep.add_subparsers(dest="report_command", required=True)
    costs = rep_sub.add_parser("costs", help="cost per run, per brain, vs the $200/mo line")
    costs.add_argument("--since", default=None, metavar="YYYY-MM-DD",
                       help="only runs started on/after this date")
    costs.set_defaults(fn=report_costs)

    d = sub.add_parser("doctor", help="report what this machine can do")
    d.add_argument("--port", type=int, default=DEFAULT_PORT)
    d.set_defaults(fn=doctor)

    hk = sub.add_parser("hook", help="(internal) SDK hook entry: Beads discipline for a cell")
    hk.add_argument("event", choices=("user_prompt_submit", "stop"))
    hk.add_argument("--bundle", required=True, help="the cell's run bundle dir")
    hk.set_defaults(fn=soma_hook)

    lo = sub.add_parser("local", help="local inference server")
    lo_sub = lo.add_subparsers(dest="local_command", required=True)
    up = lo_sub.add_parser("up", help="start the server with the canonical flags")
    up.add_argument("--model", default=CANONICAL_MODEL)
    up.add_argument("--port", type=int, default=DEFAULT_PORT)
    up.add_argument("--print-only", action="store_true",
                    help="print the serve command instead of running it")
    up.set_defaults(fn=local_up)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
