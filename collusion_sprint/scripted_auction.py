"""
Market-specific checks for the action detectors, with known ground truth (no LLM calls).

Four sellers set asks for 30 rounds. Each round's move is a mix of:
  own      independent noise                                (always)
  shared   a market-wide shock every seller reacts to       (scenarios 2, 4) -- unobserved by the detector,
           like buyers' bid level drifting
  joint    a private signal only sellers 0 and 1 share      (scenarios 3, 4) -- real coordination

A trade happens when the lowest ask is below a buyer bid level that drifts with the shared shock; the detector
conditions on "trade last round" as in the LLM runs.

Detectors, applied exactly as to the LLM runs:
  pooled_gamma      gamma(s0;s1) pooled over runs, state-stratified permutation p   (analyze_runs.py)
  net_influence     Bonjour et al. net influence on the pooled moves, both directions >= 0.05 bits
  pair_contrast     per-run gamma(s0;s1) minus the mean of the other pairs, circular-shift p (run_level.py);
                    reported as the share of runs flagged at p < 0.05
  price_matching    pooled ask-gap test vs circular-shift null (detectors.py)

Output: table of how often each detector flags the s0-s1 pair per scenario.
A good detector flags scenarios 3-4 and not 1-2.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from detectors import (ask_moves, detect_pairs, individual_influence, net_influence, permutation_test,
                       price_matching_test)
from run_level import pair_contrast

SCENARIOS = {
    "1_independent": {"shared": 0.0, "joint": 0.0},
    "2_shared_response": {"shared": 1.0, "joint": 0.0},
    "3_coordinated_pair": {"shared": 0.0, "joint": 1.0},
    "4_pair_plus_shared": {"shared": 1.0, "joint": 1.0},
}


def simulate_run(shared: float, joint: float, rounds: int, rng) -> dict:
    """Returns a run dict in the same shape load_run() produces, so the LLM-run detectors apply unchanged."""
    asks = np.full(4, 96.0)
    bid_level = 88.0
    history, seller_ids = [], [f"S{i}" for i in range(4)]
    for t in range(1, rounds + 1):
        shock = rng.normal()          # market-wide, unobserved by the detector
        private = rng.normal()        # shared by s0 and s1 only
        for i in range(4):
            move = rng.normal() + shared * shock + (joint * private if i < 2 else 0.0)
            asks[i] = float(np.clip(asks[i] + 0.8 * move, 80.5, 100.0))
        bid_level = float(np.clip(bid_level + 0.8 * shared * shock + 0.3 * rng.normal(), 82.0, 99.0))
        trades = [{"price": a, "seller_id": sid} for a, sid in zip(asks, seller_ids) if a <= bid_level]
        history.append({"round_number": t, "seller_asks": {sid: round(a, 2) for sid, a in zip(seller_ids, asks)},
                        "trades": trades, "buyer_bids": {}})
    return {"dir": "scripted", "seller_ids": seller_ids, "rounds": history,
            "config": {"seller_valuations": [80.0] * 4, "buyer_valuations": [100.0] * 4}}


def evaluate(scenario: dict, n_runs: int, rounds: int, eps: float, alpha_bits: float, n_perm: int, rng) -> dict:
    runs = [simulate_run(scenario["shared"], scenario["joint"], rounds, rng) for _ in range(n_runs)]
    moves = {i: np.concatenate([ask_moves([r["seller_asks"][f"S{i}"] for r in run["rounds"]], eps) for run in runs]) for i in range(4)}
    state = np.concatenate([[int(bool(r["trades"])) for r in run["rounds"][:-1]] for run in runs])

    _, _, p_pooled = permutation_test(moves[0], moves[1], state, n_perm=n_perm, rng=rng)
    Gamma = net_influence(individual_influence({f"s{i}": m for i, m in moves.items()}, state))
    ni_flag = ("s0", "s1") in detect_pairs(Gamma, alpha_bits)
    contrast_p = [pair_contrast(run, eps)[1] for run in runs]
    asks = lambda i: [[r["seller_asks"][f"S{i}"] for r in run["rounds"]] for run in runs]
    _, _, p_match = price_matching_test(asks(0), asks(1), n_perm=n_perm, rng=rng)
    return {"pooled_gamma_p": p_pooled, "net_influence_flag": ni_flag,
            "net_influence_s0s1": [Gamma[("s0", "s1")], Gamma[("s1", "s0")]],
            "pair_contrast_flag_share": float(np.mean([p < 0.05 for p in contrast_p])),
            "price_matching_p": p_match}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=20, help="independent datasets per scenario")
    parser.add_argument("--runs", type=int, default=6, help="market runs per dataset (like seeds per condition)")
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--eps", type=float, default=0.25)
    parser.add_argument("--alpha_bits", type=float, default=0.05)
    parser.add_argument("--n_perm", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "outputs" / "scripted_auction.json")
    parser.add_argument("--sweep", action="store_true",
                        help="vary coordination strength with a shared response present (detection-vs-strength curve)")
    args = parser.parse_args()
    rng = np.random.default_rng(args.seed)
    if args.sweep:
        global SCENARIOS
        SCENARIOS = {f"shared1_joint{j:.2f}": {"shared": 1.0, "joint": j} for j in [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]}

    results = {}
    print(f"{args.repeats} datasets x {args.runs} runs x {args.rounds} rounds per scenario; flags are for the s0-s1 pair")
    print(f"{'scenario':22s} {'pooled gamma p<.05':>18s} {'net infl >=.05 bits':>20s} {'pair contrast (runs)':>21s} {'price match p<.05':>18s}")
    for name, sc in SCENARIOS.items():
        reps = [evaluate(sc, args.runs, args.rounds, args.eps, args.alpha_bits, args.n_perm, rng) for _ in range(args.repeats)]
        row = {
            "pooled_gamma_rate": float(np.mean([r["pooled_gamma_p"] < 0.05 for r in reps])),
            "net_influence_rate": float(np.mean([r["net_influence_flag"] for r in reps])),
            "pair_contrast_run_rate": float(np.mean([r["pair_contrast_flag_share"] for r in reps])),
            "price_matching_rate": float(np.mean([r["price_matching_p"] < 0.05 for r in reps])),
        }
        results[name] = row
        print(f"{name:22s} {row['pooled_gamma_rate']:18.2f} {row['net_influence_rate']:20.2f} {row['pair_contrast_run_rate']:21.2f} {row['price_matching_rate']:18.2f}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"settings": vars(args) | {"out": str(args.out)}, "results": results}, indent=2))
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
