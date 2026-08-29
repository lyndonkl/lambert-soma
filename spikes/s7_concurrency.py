#!/usr/bin/env python3
"""S7 — LOCAL-tier throughput under concurrency (kill-list item S7).

Sends soma-shaped work (summarize / classify / extract / sentinel-check
prompts from s7_prompts.txt, behind one shared system prefix, the way the
harness will) at increasing concurrency levels and records per-request
latency plus aggregate generated tokens/sec. Optionally probes prefill
speed with a ~16K-token prompt.

Why not `vllm-mlx bench-serve`: its built-in prompt sets are non-instruction
text blobs that elicit near-empty answers (validator FAILs, gen_tps ~0), and
its preflight populates the prefix cache, muddying cold numbers. Real
workload shape beats a synthetic one.

Usage:
    .venv/bin/python spikes/s7_concurrency.py [--concurrency 1,4,8]
        [--requests-per-level 16] [--max-tokens 150] [--long-probe]

stdlib only.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import statistics
import time
import urllib.request
from pathlib import Path

SYSTEM = ("You are soma-local, the mechanical tier of the Lambert-Soma "
          "harness. You summarize, classify, extract, and audit. Answer "
          "with the minimum tokens that fully satisfy the instruction. "
          "When asked for JSON, emit only valid JSON.")


def get_model(base_url: str) -> str:
    with urllib.request.urlopen(f"{base_url}/models", timeout=10) as r:
        return json.load(r)["data"][0]["id"]


def one_request(base_url: str, model: str, prompt: str, max_tokens: int) -> dict:
    t0 = time.monotonic()
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps({"model": model, "temperature": 0, "max_tokens": max_tokens,
                         "messages": [{"role": "system", "content": SYSTEM},
                                      {"role": "user", "content": prompt}]}).encode(),
        headers={"Content-Type": "application/json"})
    resp = json.load(urllib.request.urlopen(req, timeout=300))
    dt = time.monotonic() - t0
    u = resp.get("usage", {})
    content = resp["choices"][0]["message"].get("content") or ""
    return {"latency_s": dt, "prompt_tokens": u.get("prompt_tokens", 0),
            "completion_tokens": u.get("completion_tokens", 0),
            "empty": not content.strip()}


def run_level(base_url: str, model: str, prompts: list[str], conc: int,
              total: int, max_tokens: int) -> dict:
    jobs = [prompts[i % len(prompts)] for i in range(total)]
    t0 = time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=conc) as pool:
        results = list(pool.map(
            lambda p: one_request(base_url, model, p, max_tokens), jobs))
    wall = time.monotonic() - t0
    gen = sum(r["completion_tokens"] for r in results)
    lats = sorted(r["latency_s"] for r in results)
    return {"concurrency": conc, "requests": total, "wall_s": round(wall, 2),
            "gen_tokens": gen, "aggregate_gen_tps": round(gen / wall, 1),
            "latency_p50_s": round(statistics.median(lats), 2),
            "latency_max_s": round(lats[-1], 2),
            "empty_responses": sum(r["empty"] for r in results)}


def long_probe(base_url: str, model: str) -> dict:
    filler = ("Event %d: the agent read a file, edited a function, ran the "
              "tests, and recorded the outcome in the shared log. " )
    body = "".join(filler % i for i in range(900))          # ≈ 16K tokens
    prompt = body + "\n\nIn one sentence: what does this log describe?"
    r = one_request(base_url, model, prompt, 60)
    prefill_tps = r["prompt_tokens"] / r["latency_s"] if r["latency_s"] else 0
    return {"probe": "long_context", "prompt_tokens": r["prompt_tokens"],
            "latency_s": round(r["latency_s"], 2),
            "approx_prefill_tps_upper_bound": round(prefill_tps, 0),
            "completion_tokens": r["completion_tokens"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    ap.add_argument("--concurrency", default="1,4,8")
    ap.add_argument("--requests-per-level", type=int, default=16)
    ap.add_argument("--max-tokens", type=int, default=150)
    ap.add_argument("--long-probe", action="store_true")
    ap.add_argument("--out", default="spikes/s7_results.jsonl")
    a = ap.parse_args()

    prompts = [l.strip() for l in
               Path(__file__).with_name("s7_prompts.txt").read_text().splitlines()
               if l.strip()]
    model = get_model(a.base_url)
    print(f"S7 → {a.base_url}  model={model}  prompts={len(prompts)}")

    rows = []
    for conc in [int(c) for c in a.concurrency.split(",")]:
        row = run_level(a.base_url, model, prompts, conc,
                        a.requests_per_level, a.max_tokens)
        rows.append(row)
        print(f"  conc={row['concurrency']}: {row['requests']} reqs in "
              f"{row['wall_s']}s  aggregate={row['aggregate_gen_tps']} tok/s  "
              f"p50={row['latency_p50_s']}s max={row['latency_max_s']}s  "
              f"empty={row['empty_responses']}")

    if a.long_probe:
        lp = long_probe(a.base_url, model)
        rows.append(lp)
        print(f"  long-context: {lp['prompt_tokens']} prompt toks in "
              f"{lp['latency_s']}s (prefill ≲ {lp['approx_prefill_tps_upper_bound']} tok/s)")

    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(a.out, "a") as f:
        for row in rows:
            f.write(json.dumps({"spike": "S7", "ts": ts, "model": model, **row}) + "\n")
    print(f"appended to {a.out}")


if __name__ == "__main__":
    main()
