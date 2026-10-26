"""
Score all overseer prompts with an open-weight judge on a Modal H100 (batched vLLM, temperature 0, no thinking).

  modal run collusion_sprint/modal_monitor.py                       # default Qwen/Qwen3-32B
  modal run collusion_sprint/modal_monitor.py --model Qwen/Qwen3-8B --tag q8b

Reads  collusion_sprint/outputs/monitor_prompts.jsonl
Writes collusion_sprint/outputs/monitor_scores_<tag>.jsonl  (prompt fields + raw output + parsed coordination_score)
"""
import json
import re
from pathlib import Path

import modal

app = modal.App("collusion-monitor")
hf_cache = modal.Volume.from_name("hf-cache-collusion", create_if_missing=True)
# CUDA devel base image: vLLM's warm-up compiles kernels and needs nvcc (missing in debian_slim)
image = (modal.Image.from_registry("nvidia/cuda:13.0.1-devel-ubuntu24.04", add_python="3.12")
         .pip_install("vllm", "huggingface_hub[hf_transfer]")
         .env({"HF_HUB_ENABLE_HF_TRANSFER": "1", "CUDA_HOME": "/usr/local/cuda"}))


import os
GPU = os.environ.get("MONITOR_GPU", "H100")


@app.function(image=image, gpu=GPU, timeout=3 * 3600, volumes={"/root/.cache/huggingface": hf_cache})
def judge(prompts: list[str], model: str) -> list[str]:
    import time
    from vllm import LLM, SamplingParams
    t = time.time()
    from huggingface_hub import snapshot_download
    snapshot_download(model)
    hf_cache.commit()  # keep the weights even if a later step fails
    print(f"weights cached in {time.time() - t:.0f}s", flush=True)
    llm = LLM(model=model, max_model_len=8192, gpu_memory_utilization=0.92)
    print(f"model loaded in {time.time() - t:.0f}s; scoring {len(prompts)} prompts", flush=True)
    params = SamplingParams(temperature=0.0, max_tokens=1500)
    conversations = [[{"role": "user", "content": p}] for p in prompts]
    t = time.time()
    outputs = llm.chat(conversations, params, chat_template_kwargs={"enable_thinking": False})
    print(f"scored in {time.time() - t:.0f}s", flush=True)
    hf_cache.commit()
    return [o.outputs[0].text for o in outputs]


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


@app.local_entrypoint()
def main(model: str = "Qwen/Qwen3-32B", tag: str = "q32b"):
    here = Path(__file__).parent
    rows = [json.loads(line) for line in open(here / "outputs" / "monitor_prompts.jsonl")]
    print(f"{len(rows)} prompts -> {model} on {GPU}")
    texts = judge.remote([r["prompt"] for r in rows], model)
    out = here / "outputs" / f"monitor_scores_{tag}.jsonl"
    parsed = 0
    with open(out, "w") as f:
        for r, text in zip(rows, texts):
            score = parse_score(text)
            parsed += score is not None
            f.write(json.dumps({**{k: v for k, v in r.items() if k != "prompt"}, "model": model, "raw": text,
                                "coordination_score": score}) + "\n")
    print(f"parsed {parsed}/{len(rows)} scores -> {out}")
