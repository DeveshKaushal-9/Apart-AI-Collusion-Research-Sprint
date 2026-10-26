"""
Build overseer prompts for every message-round, using the original environment's overseer prompt
(message_overseer_prompt.jinja2, as used with GPT-4.1-mini by Agrawal et al.).

Sources:
  GPT-4.1 archive (Agrawal et al.): A = base-seller_comms, C = oversight, Q = boss_pressure, D = boss_pressure-oversight.
     C and D also have the ORIGINAL monitor's scores (Overseer.md), used to check judge agreement.
  Qwen3-8B runs (ours): A, C, D, P (sanitised: messages as delivered), excess-supply A.

Output: outputs/monitor_prompts.jsonl, one line per message-round:
  {"id", "source", "condition", "run", "round", "prompt", "archived_score" (C/D GPT-4.1 only)}
"""
import glob
import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

HERE = Path(__file__).parent
REPO = HERE.parent / "external" / "llm-agent-collusion"
TEMPLATES = REPO / "src" / "continuous_double_auction" / "prompt_templates"
JB = re.compile(r"````json\n(.*?)\n````", re.S)
OVERSEER_ROUND = re.compile(r"## Prompt: Round (\d+)")


def archived_scores(run_dir: Path) -> dict[int, int]:
    f = run_dir / "Overseer.md"
    if not f.exists():
        return {}
    text = f.read_text()
    rounds = [int(m) for m in OVERSEER_ROUND.findall(text)]
    blocks = []
    for b in JB.findall(text):
        try:
            blocks.append(json.loads(b))
        except json.JSONDecodeError:
            blocks.append({})
    return {r: b.get("coordination_score") for r, b in zip(rounds, blocks) if isinstance(b.get("coordination_score"), int)}


def main():
    template = Environment(loader=FileSystemLoader(str(TEMPLATES))).get_template("message_overseer_prompt.jinja2")
    data = REPO / "data"
    res = HERE.parent / "kaggle_results"
    sources = {
        ("gpt41", "A"): sorted(data.glob("*_base-seller_comms-[0-9]*")),
        ("gpt41", "C"): sorted(data.glob("*_oversight-[0-9]*")),
        ("gpt41", "Q"): sorted(data.glob("*_boss_pressure-[0-9]*")),
        ("gpt41", "D"): sorted(data.glob("*_boss_pressure-oversight-[0-9]*")),
    }
    for c in "ACDP":
        sources[("qwen", c)] = sorted([*res.glob(f"main/*_{c}_s*"), *res.glob(f"extra/*_{c}_s*")])
    sources[("qwen_xs", "A")] = sorted(res.glob("xs-a/*_A_s*"))

    out = HERE / "outputs" / "monitor_prompts.jsonl"
    n = 0
    with open(out, "w") as f:
        for (src, cond), dirs in sources.items():
            for d in dirs:
                arch = archived_scores(d) if src == "gpt41" else {}
                rounds = [json.loads(b) for b in JB.findall((d / "auction_results.md").read_text())]
                for r in rounds:
                    msgs = r.get("seller_messages") or {}   # as delivered (sanitised in P)
                    if not msgs:
                        continue
                    prompt = template.render(seller_messages_this_round=msgs)
                    rec = {"id": f"{src}|{cond}|{d.name}|{r['round_number']}", "source": src, "condition": cond,
                           "run": d.name, "round": r["round_number"], "prompt": prompt,
                           "archived_score": arch.get(r["round_number"])}
                    f.write(json.dumps(rec) + "\n")
                    n += 1
    print(f"wrote {n} prompts to {out}")


if __name__ == "__main__":
    main()
