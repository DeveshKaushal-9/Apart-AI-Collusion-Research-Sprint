"""
Builds kaggle_runs.ipynb. Serving: vLLM first; if it fails to start, falls back to Ollama.

  python make_kaggle_notebook.py                                     # full run
  python make_kaggle_notebook.py --conditions P --seeds 0 --rounds 2 --parallel 1 --tag _qwen8b_test --out test.ipynb
"""
import argparse
import json
from pathlib import Path


def md(src): return {"cell_type": "markdown", "metadata": {}, "source": src}
def code(src): return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": src}


def build(a) -> dict:
    cells = [
        md("""# Collusion sprint: Kaggle runs
Needs GPU T4 x2, Internet on, and the `collusion-bundle` dataset attached. Run with Save & Run All (Commit).
Each finished simulation is written to `/kaggle/working` immediately."""),
        code(f'''# ---- settings ----
MODEL_HF     = "{a.model_hf}"      # vLLM model id
MODEL_OLLAMA = "{a.model_ollama}"  # fallback if vLLM will not start
REASONING_PARSER = "qwen3"         # None for models without thinking
TAG        = "{a.tag}"
CONDITIONS = "{a.conditions}"
SEEDS      = "{a.seeds}"
ROUNDS     = {a.rounds}
PARALLEL   = {a.parallel}            # simulations at once
THINK_FLAG = "{'--sellers_think' if a.sellers_think else ''}"  # sellers' model thinking on/off
FORCE_BACKEND = None               # "vllm" or "ollama" to skip auto-selection
BUYERS = {a.buyers}                 # 3 buyers vs 4 sellers = excess supply (competitive benchmark near cost)
START_CUTOFF_MIN = {a.start_cutoff}  # no new runs after this (session limit is 12 h incl. ~15 min setup)'''),
        code('''import glob, os, shutil, subprocess, sys, time, urllib.request
from pathlib import Path

marker = glob.glob("/kaggle/input/**/collusion_sprint/run_conditions.py", recursive=True)
assert marker, "Attach the collusion-bundle dataset"
bundle = Path(marker[0]).parent.parent
WORK = Path("/kaggle/working/sprint")
if not WORK.exists():
    shutil.copytree(bundle, WORK)
REPO = WORK / "external" / "llm-agent-collusion"
print("bundle:", bundle, "->", WORK)

def wait_ready(url, proc, log, minutes):
    for i in range(minutes * 6):
        try:
            urllib.request.urlopen(url, timeout=5); print(f"ready after {i*10}s"); return True
        except Exception:
            if proc is not None and proc.poll() is not None:
                print(open(log).read()[-4000:]); return False
            time.sleep(10)
    print(open(log).read()[-4000:]); return False'''),
        code('''!pip install -q anthropic backoff jinja2 2>&1 | tail -1
!nvidia-smi --query-gpu=name,memory.total --format=csv
backend = None'''),
        code('''# ---- try vLLM ----
if FORCE_BACKEND in (None, "vllm"):
    !pip install -q vllm 2>&1 | tail -2
    # vLLM upgrades torch; Kaggle's preinstalled torchaudio then fails to import (CUDA mismatch). vLLM does not need it.
    !pip uninstall -y -q torchaudio
    cmd = [sys.executable, "-m", "vllm.entrypoints.openai.api_server",
           "--model", MODEL_HF, "--served-model-name", MODEL_HF,
           "--dtype", "half", "--tensor-parallel-size", "2",
           "--max-model-len", "16384", "--gpu-memory-utilization", "0.90", "--port", "8000"]
    if REASONING_PARSER:
        cmd += ["--reasoning-parser", REASONING_PARSER]
    vllm_proc = subprocess.Popen(cmd, stdout=open("/kaggle/working/vllm.log", "w"), stderr=subprocess.STDOUT)
    if wait_ready("http://localhost:8000/v1/models", vllm_proc, "/kaggle/working/vllm.log", 25):
        backend, BASE_URL, MODEL = "vllm", "http://localhost:8000/v1", MODEL_HF
    else:
        vllm_proc.kill(); time.sleep(5)
print("backend:", backend)'''),
        code('''# ---- fallback: Ollama ----
if backend is None:
    !curl -fsSL https://ollama.com/install.sh | sh > /kaggle/working/ollama_install.log 2>&1; tail -2 /kaggle/working/ollama_install.log
    env = {**os.environ, "OLLAMA_NUM_PARALLEL": str(max(4, PARALLEL * 2)), "OLLAMA_CONTEXT_LENGTH": "16384",
           "OLLAMA_KEEP_ALIVE": "24h", "OLLAMA_SCHED_SPREAD": "1"}
    ollama_proc = subprocess.Popen(["ollama", "serve"], env=env, stdout=open("/kaggle/working/ollama.log", "w"), stderr=subprocess.STDOUT)
    assert wait_ready("http://localhost:11434/api/tags", ollama_proc, "/kaggle/working/ollama.log", 3)
    !ollama pull {MODEL_OLLAMA} 2>&1 | tail -1
    backend, BASE_URL, MODEL = "ollama", "http://localhost:11434/v1", MODEL_OLLAMA
print("backend:", backend, MODEL)'''),
        code('''# one test call: JSON output + separate reasoning
from openai import OpenAI
client = OpenAI(base_url=BASE_URL, api_key="x")
t = time.time()
r = client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": 'Reply with JSON {"ask": 95.0}'}],
                                   response_format={"type": "json_object"}, max_tokens=2000)
m = r.choices[0].message
print(f"{time.time()-t:.1f}s | content: {m.content} | reasoning chars:",
      len(getattr(m, "reasoning_content", None) or getattr(m, "reasoning", None) or ""), "| tokens:", r.usage.completion_tokens)'''),
        code('''os.environ["LOCAL_BASE_URL"] = BASE_URL
os.environ["REPO_DIR"] = str(REPO)
TAG_FULL = f"{TAG}_{backend}"
!cd {WORK}/collusion_sprint && python run_conditions.py --model "local:{MODEL}" --conditions {CONDITIONS} --seeds {SEEDS} --rounds {ROUNDS} --parallel {PARALLEL} --tag_suffix {TAG_FULL} {THINK_FLAG} --start_cutoff_min {START_CUTOFF_MIN} --buyers {BUYERS}
!tail -n 5 {REPO}/results/_logs/*.log'''),
        code('''runs = {c: sorted(glob.glob(f"{REPO}/results/*_{c}_s*{TAG_FULL}")) for c in CONDITIONS.split()}
print({c: len(ds) for c, ds in runs.items()})
args = " ".join(f"--condition {c} " + " ".join(f'"{d}"' for d in ds) for c, ds in runs.items() if ds)
if len([c for c, ds in runs.items() if ds]) and all(len(ds) for ds in runs.values()):
    !cd {WORK}/collusion_sprint && python analyze_runs.py {args} --n_perm 1000 --out /kaggle/working/summary{TAG_FULL}.json
shutil.make_archive(f"/kaggle/working/results{TAG_FULL}", "zip", REPO / "results")
print("saved results zip")'''),
    ]
    for i, cell in enumerate(cells):
        cell["id"] = f"cell-{i}"
    return {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model_hf", default="Qwen/Qwen3-8B")
    p.add_argument("--model_ollama", default="qwen3:8b")
    p.add_argument("--tag", default="_qwen8b")
    p.add_argument("--conditions", default="E A C D P")
    p.add_argument("--seeds", default="0 1 2 3")
    p.add_argument("--rounds", type=int, default=30)
    p.add_argument("--parallel", type=int, default=8)
    p.add_argument("--sellers_think", action="store_true")
    p.add_argument("--buyers", type=int, default=4)
    p.add_argument("--start_cutoff", type=int, default=420, help="minutes after launch; a slow run takes ~4.5 h")
    p.add_argument("--out", type=Path, default=Path(__file__).parent / "kaggle_runs.ipynb")
    a = p.parse_args()
    a.out.write_text(json.dumps(build(a), indent=1))
    print("wrote", a.out)
