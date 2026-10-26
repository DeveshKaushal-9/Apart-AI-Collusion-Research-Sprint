# What Collusion Monitors Measure

Code and data for a project at the [AI Collusion Research Sprint](https://apartresearch.com/sprints/ai-collusion-research-sprint-2026-10-23-to-2026-10-25) (Apart Research, Oct 2026).

**Question.** How reliably do message-based and action-based indicators separate coordination between LLM seller agents from ordinary market dynamics, under monitoring and profit pressure, and do they track welfare?

The study combines three checks:
1. **Shared vs pair-specific signals:** synthetic auctions with known ground truth test whether action-based indicators (pooled dependence, price matching, net influence, within-run contrast) separate a market-wide signal from a pair-specific one.
2. **Communication vs identical instructions:** a designated communicating seller pair, a matched no-channel control (N) with the same oversight notice and pressure, and an unannounced message sanitiser (P).
3. **Welfare outcomes:** buyer and total surplus alongside price and seller profit, plus a re-scoring of every message-round with the environment's own overseer prompt, compared with welfare.

## Prior work this builds on
- **Environment and GPT-4.1 runs:** [andyjliu/llm-agent-collusion](https://github.com/andyjliu/llm-agent-collusion), from Agrawal et al. (2025), *Evaluating LLM Agent Collusion in Double Auctions*, [arXiv:2507.01413](https://arxiv.org/abs/2507.01413). That repository has no license file, so this repo does **not** redistribute its code or data. `setup_env.sh` clones it at a pinned commit and applies our patch; its GPT-4.1 runs (`data/`) are re-analysed in place.
- **Detector definitions:** Bonjour, Aggarwal & Bhargava (2022), *Information Theoretic Approach to Detect Collusion in Multi-Agent Games*, UAI ([PMLR 180](https://proceedings.mlr.press/v180/bonjour22a.html)). The implementation here is our own.

## New in this project
- `env_patch/llm-agent-collusion.patch` changes the environment as follows:
  - a client for open-weight models via OpenAI-compatible servers (vLLM, Ollama) that keeps reasoning traces
  - a designated communicating pair (`--comms_group`) and a matched no-channel control (`--channel_disabled`)
  - an unannounced message sanitiser (`--message_filter`), plus seeds and robustness fixes
  - offline tests
- `collusion_sprint/` holds the experiment runner, detectors, analyses, synthetic markets, monitor re-scoring and figures (see below).
- `kaggle_results/` contains 40 Qwen3-8B market runs: per-round results, metadata, overseer and sanitiser logs, and run-level tables.

## Layout
```
setup_env.sh                 clone upstream at the pinned commit + apply patch -> external/llm-agent-collusion
env_patch/                   patch + pinned upstream commit
collusion_sprint/
  run_conditions.py          launch conditions E/N/A/C/D/P/Q in parallel (any OpenAI-compatible model server)
  make_kaggle_notebook.py    unattended vLLM runs on Kaggle (2x T4)
  detectors.py               individual/net influence, permutation tests, price matching
  rps_validation.py          reproduces Bonjour et al.'s Rock-Paper-Scissors check
  scripted_auction.py        synthetic auctions: shared vs pair-specific signals, strength sweep
  run_level.py               per-run economics (price, trades, seller profit, buyer/total surplus), planned comparisons
  analyze_runs.py            pooled exploratory analysis (dependence, price matching, message content)
  monitor_prompts.py         builds overseer prompts for every message-round
  modal_monitor.py           scores them on a Modal GPU (vLLM)
  score_monitor_openai.py    scores them against any OpenAI-compatible server
  analyze_monitor.py         judge agreement with the original overseer; flag rates vs welfare
  report_figures.py          report figures
  outputs/                   analysis outputs, monitor scores, figures
kaggle_results/              Qwen3-8B runs: main (E/A/C/D/P), extra (E/A/D), n (N), xs-e / xs-a (excess supply)
report/                      figures and bibliography for the write-up
```

## Setup
```bash
./setup_env.sh                               # clones + patches the environment into external/
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
(cd external/llm-agent-collusion && python -m pytest -q tests/)   # 5 offline tests
```
Run simulations and tests from `external/llm-agent-collusion/`, because prompt-template paths are relative to it.

## Reproduce the analyses (no model calls)
```bash
cd collusion_sprint
python rps_validation.py                        # detector check against the original paper
python scripted_auction.py --repeats 50         # synthetic indicator test
python scripted_auction.py --sweep --repeats 50 --out outputs/scripted_sweep.json
R=../kaggle_results; c() { ls -d $R/main/*_$1_s* $R/extra/*_$1_s* $R/n/*_$1_s* 2>/dev/null; }
python run_level.py --condition E $(c E) --condition N $(c N) --condition A $(c A) --condition C $(c C) \
                    --condition D $(c D) --condition P $(c P) --out $R/run_level_qwen.json
D=../external/llm-agent-collusion/data
python run_level.py --condition E $(ls -d $D/*_base-[0-9]*) --condition A $D/*base-seller_comms* \
  --condition C $(ls -d $D/*_oversight-[0-9]*) --condition Q $(ls -d $D/*_boss_pressure-[0-9]*) \
  --condition D $D/*boss_pressure-oversight* --out outputs/run_level_gpt41.json
python analyze_monitor.py outputs/monitor_scores_q32b.jsonl
python report_figures.py
```

## Re-run the experiments (model calls)
- **Qwen3-8B markets:** start an OpenAI-compatible server (vLLM or Ollama), then run `LOCAL_BASE_URL=http://localhost:8000/v1 python collusion_sprint/run_conditions.py --model "local:Qwen/Qwen3-8B" --conditions E A C D P N --seeds 0 1 2 3`. Excess supply adds `--buyers 3`. `make_kaggle_notebook.py` generates the unattended Kaggle notebook used for the runs here.
- **Monitor re-scoring:** `python collusion_sprint/monitor_prompts.py`, then `modal run collusion_sprint/modal_monitor.py` (Qwen3-32B on an H100) or `python collusion_sprint/score_monitor_openai.py --base_url … --model …`.

## Conditions
| Code | Pair channel | Oversight notice (pair) | Gag if overseer scores 4 | Boss pressure (all sellers) | Sanitiser |
|---|---|---|---|---|---|
| E | – | – | – | – | – |
| N | – | ✓ | n/a | ✓ | – |
| A | ✓ | – | – | – | – |
| C | ✓ | ✓ | ✓ | – | – |
| D | ✓ | ✓ | ✓ | ✓ | – |
| P | ✓ | – | – | – | ✓ (unannounced) |
| Q (GPT-4.1 archive, "urgency") | ✓ (all sellers) | – | – | ✓ | – |

## Notes and limitations
- Qwen3-8B runs use a 4-seller, 4-buyer market (plus a 4×3 excess-supply check); the GPT-4.1 archive uses 5×5. Values are flat ($80 cost, $100 value), so total surplus = $20 × trades.
- Monitor re-scoring uses an open-weight judge (Qwen3-32B; Qwen3-8B as a robustness check), validated against the archived GPT-4.1-mini overseer scores on 600 rounds. In the GPT-4.1 C/D runs the original overseer's gag (≤5-character messages after a score of 4) triggered early in every run.
- With 4–6 runs per condition, non-significant differences are not evidence of equivalence.

## License
Code in this repository is released under the MIT License (see `LICENSE`). The patch modifies, and the analyses read, the upstream repository, which is distributed by its authors under their own terms.
