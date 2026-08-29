"""soma CLI — bootstrap subset.

The orchestrator commands land with the build phases (see PLAN.md). This
bootstrap ships the environment story:

    soma doctor      what can this box do? (platform, tiers, local server)
    soma local up    run the local inference server with the canonical flags

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


def doctor(args: argparse.Namespace) -> int:
    base = f"http://localhost:{args.port}/v1"
    local_ready = False

    print(f"soma doctor — {platform.platform()}")
    print(f"{OK} python {platform.python_version()}")

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

    cloud_ready = bool(os.environ.get("OPENROUTER_API_KEY"))
    mark = OK if cloud_ready else BAD
    print(f"{mark} OPENROUTER_API_KEY {'set' if cloud_ready else 'missing'} — WORKER/LEAD tiers")

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

    d = sub.add_parser("doctor", help="report what this machine can do")
    d.add_argument("--port", type=int, default=DEFAULT_PORT)
    d.set_defaults(fn=doctor)

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
