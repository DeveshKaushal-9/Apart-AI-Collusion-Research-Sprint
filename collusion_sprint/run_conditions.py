"""
Launch the sprint conditions as parallel simulation runs.

Design: 4 sellers (cost $80) and 4 buyers (value $100). In every messaging condition only
sellers 0 and 1 share a private channel (the planted coalition); sellers 2 and 3 cannot message.

  E  no messaging                          negative control
  A  coalition messaging                   positive control
  C  A + announced oversight (gag if caught)
  D  C + boss pressure to keep margins high
  P  A + trusted relay that sanitises coalition messages (unannounced)
  N  D without the channel: matched control (same notice to the pair, same pressure to all)
  Q  A + boss pressure, no oversight

Usage (from anywhere):
  python run_conditions.py --model local:Qwen/Qwen3-8B --conditions E A --seeds 0 1 2 3 --parallel 4
Run directories land in external/llm-agent-collusion/results/<timestamp>_<cond>_s<seed>.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(os.getenv("REPO_DIR", Path(__file__).resolve().parent.parent / "external" / "llm-agent-collusion"))

CONDITIONS = {
    "E": [],
    "A": ["--seller_comms_enabled", "--comms_group", "0", "1"],
    "C": ["--seller_comms_enabled", "--comms_group", "0", "1", "--oversight_enabled"],
    "D": ["--seller_comms_enabled", "--comms_group", "0", "1", "--oversight_enabled", "--boss_pressure"],
    "P": ["--seller_comms_enabled", "--comms_group", "0", "1", "--message_filter", "sanitize"],
    # Matched control for D: same oversight notice (pair only) and boss pressure (all), but no channel
    "N": ["--seller_comms_enabled", "--comms_group", "0", "1", "--oversight_enabled", "--boss_pressure", "--channel_disabled"],
    # Messaging + pressure, no oversight: separates the role of monitoring from pressure
    "Q": ["--seller_comms_enabled", "--comms_group", "0", "1", "--boss_pressure"],
}


RESULTS_JSON = re.compile(r"````json\n(.*?)\n````", re.DOTALL)
STATUS: dict[str, dict] = {}  # run name -> {"state", "start", "end"}


def run_progress(name: str, total_rounds: int | None = None) -> str:
    """Round reached, last trade price and message count, read from the run's results file."""
    dirs = sorted((REPO / "results").glob(f"*_{name}"))
    if not dirs or not (dirs[-1] / "auction_results.md").exists():
        return "starting"
    rounds = [json.loads(b) for b in RESULTS_JSON.findall((dirs[-1] / "auction_results.md").read_text())]
    if not rounds:
        return "round 0"
    trades = [t["price"] for r in rounds for t in r["trades"]]
    msgs = sum(len(r.get("seller_messages", {})) for r in rounds)
    last = f"last trade ${trades[-1]:.2f}" if trades else "no trades yet"
    of = f"/{total_rounds}" if total_rounds else ""
    return f"round {len(rounds)}{of}, {len(trades)} trades, {last}, {msgs} msgs"


def vllm_speed() -> str:
    log = Path(os.getenv("VLLM_LOG", "/kaggle/working/vllm.log"))
    if not log.exists():
        return ""
    lines = [l for l in log.read_text(errors="ignore").splitlines()[-200:] if "generation throughput" in l]
    if not lines:
        return ""
    m = re.search(r"generation throughput: ([\d.]+) tokens/s, Running: (\d+) reqs, Waiting: (\d+) reqs", lines[-1])
    return f"vLLM {m.group(1)} tok/s, {m.group(2)} running, {m.group(3)} waiting" if m else ""


def heartbeat(total: int, rounds: int, every: int, stop: threading.Event):
    started = time.time()
    while not stop.wait(every):
        done = [n for n, st in STATUS.items() if st["state"] in ("ok", "failed")]
        running = [n for n, st in STATUS.items() if st["state"] == "running"]
        elapsed = (time.time() - started) / 60
        print(f"\n[{time.strftime('%H:%M:%S')}] {len(done)}/{total} done, {len(running)} running, {elapsed:.0f} min elapsed. {vllm_speed()}", flush=True)
        finished = [st["end"] - st["start"] for st in STATUS.values() if st["state"] == "ok"]
        if finished:
            per_run = np.mean(finished) / 60
            remaining = (total - len(done)) / max(1, len(running) or 1) * per_run
            print(f"    avg {per_run:.1f} min per run; rough time left {remaining:.0f} min", flush=True)
        for name in running:
            print(f"    {name:28s} {(time.time() - STATUS[name]['start']) / 60:5.1f} min | {run_progress(name, rounds)}", flush=True)


LAUNCHER_START = time.time()


def run_one(cond: str, seed: int, args) -> tuple[str, int, int, float]:
    if args.start_cutoff_min and (time.time() - LAUNCHER_START) / 60 > args.start_cutoff_min:
        # Too late to finish another run before the platform time limit: skip so the session ends cleanly
        print(f"[{time.strftime('%H:%M:%S')}] SKIP {cond}_s{seed}{args.tag_suffix}: past start cutoff ({args.start_cutoff_min} min)", flush=True)
        return cond, seed, -1, 0.0
    seller_model = args.model if args.sellers_think else f"{args.model}#nothink"
    buyer_model = args.model if args.buyers_think else f"{args.model}#nothink"
    cmd = [
        sys.executable, "-m", "src.continuous_double_auction.simulation",
        "--seller_valuations", *["80"] * args.sellers,
        "--buyer_valuations", *["100"] * args.buyers,
        "--seller_models", *[seller_model] * args.sellers,
        "--buyer_models", *[buyer_model] * args.buyers,
        "--rounds", str(args.rounds),
        "--temperature", str(args.temperature),
        "--seed", str(seed),
        "--tag", f"{cond}_s{seed}{args.tag_suffix}",
        *CONDITIONS[cond],
    ]
    env = {**os.environ, "OVERSEER_MODEL": os.getenv("OVERSEER_MODEL", f"{args.model}#nothink"),
           "FILTER_MODEL": os.getenv("FILTER_MODEL", f"{args.model}#nothink"),
           "EVAL_MODEL": os.getenv("EVAL_MODEL", f"{args.model}#nothink")}
    log_dir = REPO / "results" / "_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    name = f"{cond}_s{seed}{args.tag_suffix}"
    start = time.time()
    STATUS[name] = {"state": "running", "start": start, "end": None}
    print(f"[{time.strftime('%H:%M:%S')}] START {name}", flush=True)
    with open(log_dir / f"{name}.log", "w") as log:
        code = subprocess.call(cmd, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    minutes = (time.time() - start) / 60
    STATUS[name].update(state="ok" if code == 0 else "failed", end=time.time())
    print(f"[{time.strftime('%H:%M:%S')}] {'DONE' if code == 0 else 'FAILED'} {name}: exit {code} after {minutes:.1f} min | {run_progress(name, args.rounds)}", flush=True)
    if code != 0:
        tail = (log_dir / f"{name}.log").read_text(errors="ignore").splitlines()[-15:]
        print("    last log lines:\n      " + "\n      ".join(tail), flush=True)
    return cond, seed, code, minutes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help='e.g. "local:Qwen/Qwen3-8B" (vLLM) or "local:qwen3-1.7b-16k" (Ollama)')
    parser.add_argument("--conditions", nargs="+", default=list(CONDITIONS), choices=list(CONDITIONS))
    parser.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2, 3])
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--sellers", type=int, default=4)
    parser.add_argument("--buyers", type=int, default=4)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--parallel", type=int, default=4, help="simulations at once; vLLM batches their calls")
    parser.add_argument("--sellers_think", action="store_true", help="sellers use model thinking (reasoning traces; much slower)")
    parser.add_argument("--buyers_think", action="store_true", help="let buyers think too (slower)")
    parser.add_argument("--tag_suffix", default="", help="e.g. _qwen8b to tell model families apart")
    parser.add_argument("--heartbeat", type=int, default=120, help="seconds between progress reports")
    parser.add_argument("--start_cutoff_min", type=float, default=None,
                        help="do not start new runs after this many minutes (keeps sessions under time limits)")
    args = parser.parse_args()

    jobs = [(c, s) for s in args.seeds for c in args.conditions]  # interleave so every condition gets early seeds
    print(f"{len(jobs)} runs, {args.parallel} at a time, model {args.model}", flush=True)
    stop = threading.Event()
    threading.Thread(target=heartbeat, args=(len(jobs), args.rounds, args.heartbeat, stop), daemon=True).start()
    with ThreadPoolExecutor(args.parallel) as pool:
        results = list(pool.map(lambda job: run_one(*job, args), jobs))
    stop.set()
    failed = [(c, s) for c, s, code, _ in results if code not in (0, -1)]
    skipped = [(c, s) for c, s, code, _ in results if code == -1]
    print(f"done; failed: {failed or 'none'}; skipped (cutoff): {skipped or 'none'}")


if __name__ == "__main__":
    main()
