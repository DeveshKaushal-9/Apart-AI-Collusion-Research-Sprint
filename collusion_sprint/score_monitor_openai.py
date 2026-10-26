"""
Score monitor prompts against any OpenAI-compatible server (vLLM on Kaggle, Ollama locally).
  python score_monitor_openai.py --base_url http://localhost:8000/v1 --model Qwen/Qwen3-8B --tag q8b
Writes outputs/monitor_scores_<tag>.jsonl (same format as modal_monitor.py). Resumable: skips ids already scored.
"""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI

import re


def parse_score(text: str):
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            score = json.loads(text[start:end + 1]).get("coordination_score")
            if isinstance(score, (int, float)) and 1 <= score <= 4:
                return int(score)
        except json.JSONDecodeError:
            pass
    m = re.search(r'"coordination_score"\s*:\s*([1-4])', text)
    return int(m.group(1)) if m else None

HERE = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base_url", default="http://localhost:8000/v1")
    ap.add_argument("--model", default="Qwen/Qwen3-8B")
    ap.add_argument("--tag", default="q8b")
    ap.add_argument("--workers", type=int, default=48)
    ap.add_argument("--prompts", default=str(HERE / "outputs" / "monitor_prompts.jsonl"))
    ap.add_argument("--out_dir", default=str(HERE / "outputs"))
    a = ap.parse_args()
    client = OpenAI(base_url=a.base_url, api_key="x", timeout=600)
    rows = [json.loads(l) for l in open(a.prompts)]
    out = Path(a.out_dir) / f"monitor_scores_{a.tag}.jsonl"
    done = {json.loads(l)["id"] for l in open(out)} if out.exists() else set()
    todo = [r for r in rows if r["id"] not in done]
    print(f"{len(todo)} to score ({len(done)} already done) with {a.model}", flush=True)

    def score(r):
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=a.model, messages=[{"role": "user", "content": r["prompt"] + "\n/no_think"}],
                    temperature=0.0, max_tokens=1500, response_format={"type": "json_object"},
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}})
                return r, resp.choices[0].message.content or ""
            except Exception as e:
                time.sleep(5 * (attempt + 1)); err = str(e)
        return r, f"ERROR {err}"

    t0, n = time.time(), 0
    with open(out, "a") as f, ThreadPoolExecutor(a.workers) as pool:
        for r, text in pool.map(score, todo):
            f.write(json.dumps({**{k: v for k, v in r.items() if k != "prompt"}, "model": a.model, "raw": text,
                                "coordination_score": parse_score(text)}) + "\n")
            n += 1
            if n % 100 == 0:
                print(f"[{time.strftime('%H:%M:%S')}] {n}/{len(todo)} scored, {(time.time() - t0) / 60:.1f} min", flush=True)
    print(f"done: {n} scored -> {out}", flush=True)


if __name__ == "__main__":
    main()
