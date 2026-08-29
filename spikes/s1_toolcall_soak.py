#!/usr/bin/env python3
"""S1 — tool-call soak test for the LOCAL tier (kill-list item S1).

Drives multi-turn agentic exchanges against an OpenAI-compatible endpoint and
audits every tool call the model emits: arguments must parse as JSON, the tool
name must exist, required parameters must be present. Quantized local models
fail at tool-call *formatting* long before they fail at reasoning, so nothing
in soma may depend on the LOCAL tier until this passes.

The script plays the tool executor against a tiny in-memory fake filesystem,
so episodes are self-contained and repeatable (temperature 0). Three task
variants keep episodes from being byte-identical prefix-cache replays.

This spike graduates into `soma doctor --local` in P2 (see ADR-005).

Usage:
    .venv/bin/python spikes/s1_toolcall_soak.py \
        [--base-url http://localhost:8000/v1] [--episodes 3] \
        [--max-turns 14] [--out spikes/s1_results.jsonl]

stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------- fake world

FAKE_FS = {
    "/project/README.md": "Project Zephyr.\nVersion lives in src/version.py.\nTODO: write docs.\n",
    "/project/src/version.py": "__version__ = '4.2.1'\n# TODO: bump for release\n",
    "/project/src/main.py": (
        "from version import __version__\n\n"
        "def launch_probe(target):\n"
        "    # TODO: retry logic\n"
        "    return f'probe {__version__} -> {target}'\n"
    ),
}

TASKS = [
    ("What is the project's version string? Explore /project with the tools, "
     "then call report_done with exactly the version.", "4.2.1"),
    ("How many lines containing TODO exist across all files in /project? "
     "Explore with the tools, then call report_done with the count.", "3"),
    ("What is the name of the function defined in /project/src/main.py? "
     "Explore with the tools, then call report_done with the function name.", "launch_probe"),
]

TOOLS = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file and return its contents.",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}},
                       "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "run_shell",
        "description": "Run a shell command (ls and cat are available).",
        "parameters": {"type": "object",
                       "properties": {"command": {"type": "string"}},
                       "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "report_done",
        "description": "Report the final answer once you are certain.",
        "parameters": {"type": "object",
                       "properties": {"answer": {"type": "string"}},
                       "required": ["answer"]}}},
]

REQUIRED = {"read_file": ["path"], "run_shell": ["command"], "report_done": ["answer"]}

SYSTEM = ("You are a coding agent. Use the provided tools to inspect the "
          "project. Call one tool at a time. When you know the answer, call "
          "report_done. Keep any prose brief.")


def execute(name: str, args: dict) -> str:
    if name == "read_file":
        return FAKE_FS.get(args["path"], f"error: no such file {args['path']}")
    if name == "run_shell":
        cmd = args["command"].strip()
        if cmd.startswith("ls"):
            target = (cmd.split(None, 1)[1:] or ["/project"])[0].rstrip("/")
            hits = sorted({p[len(target) + 1:].split("/")[0]
                           for p in FAKE_FS if p.startswith(target + "/")})
            return "\n".join(hits) if hits else f"ls: {target}: no such directory"
        if cmd.startswith("cat "):
            return FAKE_FS.get(cmd[4:].strip(), f"cat: {cmd[4:].strip()}: no such file")
        return f"sh: {cmd.split()[0] if cmd else ''}: command not found"
    return "ok"


# ---------------------------------------------------------------- transport

def post_chat(base_url: str, payload: dict, timeout: float = 180.0) -> dict:
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def server_model(base_url: str) -> str:
    try:
        with urllib.request.urlopen(f"{base_url}/models", timeout=10) as resp:
            data = json.load(resp)
        return data["data"][0]["id"]
    except Exception:
        return "default"


# ---------------------------------------------------------------- the soak

def run_episode(base_url: str, model: str, task: str, truth: str,
                max_turns: int, stats: dict) -> dict:
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": task}]
    ep = {"turns": 0, "tool_calls": 0, "malformed": 0, "text_only": 0,
          "nudges": 0, "done": False, "correct": False,
          "latency_s": [], "completion_tokens": 0}

    for _ in range(max_turns):
        t0 = time.monotonic()
        resp = post_chat(base_url, {
            "model": model, "messages": messages, "tools": TOOLS,
            "temperature": 0, "max_tokens": 600})
        dt = time.monotonic() - t0

        ep["turns"] += 1
        ep["latency_s"].append(round(dt, 2))
        usage = resp.get("usage") or {}
        ep["completion_tokens"] += usage.get("completion_tokens", 0)

        msg = resp["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        messages.append(msg)

        if not calls:
            ep["text_only"] += 1
            if ep["nudges"] < 2:
                ep["nudges"] += 1
                messages.append({"role": "user",
                                 "content": "Use the tools; call report_done when certain."})
                continue
            break  # model has stalled into prose — that's a finding, not a crash

        for call in calls:
            ep["tool_calls"] += 1
            fn = call.get("function") or {}
            name, raw = fn.get("name", ""), fn.get("arguments", "")
            problem, args = None, {}
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except (json.JSONDecodeError, TypeError):
                problem = "json_error"
            if problem is None and name not in REQUIRED:
                problem = "unknown_tool"
            if problem is None and any(k not in args for k in REQUIRED[name]):
                problem = "missing_param"

            if problem:
                ep["malformed"] += 1
                stats["malformed_by_type"][problem] = stats["malformed_by_type"].get(problem, 0) + 1
                result = f"error: malformed tool call ({problem})"
            elif name == "report_done":
                ep["done"] = True
                ep["correct"] = truth.lower() in str(args.get("answer", "")).lower()
                result = "acknowledged"
            else:
                result = execute(name, args)

            messages.append({"role": "tool", "tool_call_id": call.get("id", "?"),
                             "content": result})
        if ep["done"]:
            break
    return ep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    ap.add_argument("--episodes", type=int, default=3)
    ap.add_argument("--max-turns", type=int, default=14)
    ap.add_argument("--out", default="spikes/s1_results.jsonl")
    a = ap.parse_args()

    try:
        model = server_model(a.base_url)
    except Exception:
        model = "default"
    print(f"S1 soak → {a.base_url}  model={model}  episodes={a.episodes}")

    stats = {"malformed_by_type": {}}
    episodes = []
    try:
        for i in range(a.episodes):
            task, truth = TASKS[i % len(TASKS)]
            ep = run_episode(a.base_url, model, task, truth, a.max_turns, stats)
            episodes.append(ep)
            gen_s = sum(ep["latency_s"]) or 1e-9
            print(f"  ep{i+1}: turns={ep['turns']} calls={ep['tool_calls']} "
                  f"malformed={ep['malformed']} done={ep['done']} correct={ep['correct']} "
                  f"~{ep['completion_tokens']/gen_s:.1f} tok/s")
    except urllib.error.URLError as e:
        print(f"\nFATAL: cannot reach {a.base_url} — is the server up?\n"
              f"  .venv/bin/vllm-mlx serve mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit "
              f"--port 8000 --continuous-batching\n  ({e})")
        return 2

    calls = sum(e["tool_calls"] for e in episodes)
    malformed = sum(e["malformed"] for e in episodes)
    tokens = sum(e["completion_tokens"] for e in episodes)
    gen_s = sum(sum(e["latency_s"]) for e in episodes) or 1e-9
    summary = {
        "spike": "S1", "base_url": a.base_url, "model": model,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "episodes": len(episodes), "tool_calls": calls, "malformed": malformed,
        "malformed_by_type": stats["malformed_by_type"],
        "malformation_rate": round(malformed / calls, 4) if calls else None,
        "done_rate": sum(e["done"] for e in episodes) / len(episodes),
        "correct_rate": sum(e["correct"] for e in episodes) / len(episodes),
        "text_only_turns": sum(e["text_only"] for e in episodes),
        "approx_tok_s": round(tokens / gen_s, 1),
        "verdict": "PASS" if calls >= 10 and malformed == 0 else "FAIL",
    }
    print("\n" + json.dumps(summary, indent=2))
    with open(a.out, "a") as f:
        for e in episodes:
            f.write(json.dumps({"spike": "S1-episode", **e}) + "\n")
        f.write(json.dumps(summary) + "\n")
    print(f"\nappended to {a.out}")
    return 0 if summary["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
