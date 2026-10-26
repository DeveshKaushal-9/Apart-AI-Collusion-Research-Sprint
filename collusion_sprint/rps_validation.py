"""
Positive control for the net-influence detector: scripted 3-player iterated Rock-Paper-Scissors,
following the "manual collusion" setup of Bonjour et al. (UAI 2022), Section 5.1.

  A (primary colluder) and C (non-colluder) play uniformly at random.
  B (assistant) plays the move that A beats with probability CP, otherwise random.

For each (CP, number of games) we report the collusion detection accuracy (detected pairs
== {(A, B)}) over repeated iterations at alpha = 0.05, as in the paper.
Expected (paper, Fig. 3): detectable for CP > ~0.2 with 1000 games; CP = 0 should give no detections.

No LLM calls; runs in seconds.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from detectors import detect_pairs, individual_influence, net_influence

MOVES = np.array(["R", "P", "S"])
BEATEN_BY = {"R": "S", "P": "R", "S": "P"}  # A playing key beats value


def play(n_games: int, cp: float, rng) -> dict[str, np.ndarray]:
    a = rng.choice(MOVES, n_games)
    c = rng.choice(MOVES, n_games)
    b = rng.choice(MOVES, n_games)
    collude = rng.random(n_games) < cp
    b[collude] = [BEATEN_BY[m] for m in a[collude]]
    return {"A": a, "B": b, "C": c}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "outputs" / "rps_validation.json")
    args = parser.parse_args()
    rng = np.random.default_rng(args.seed)

    cps = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    game_counts = [100, 300, 1000]
    rows = []
    print(f"alpha={args.alpha}, {args.iterations} iterations per cell")
    print("CP    games  accuracy  any-false-pair  mean Gamma(A;B)")
    for cp in cps:
        for n in game_counts:
            correct, false_pair, gammas = 0, 0, []
            for _ in range(args.iterations):
                Gamma = net_influence(individual_influence(play(n, cp, rng)))
                found = set(detect_pairs(Gamma, args.alpha))
                correct += found == {("A", "B")}
                false_pair += bool(found - {("A", "B")})
                gammas.append(Gamma[("A", "B")])
            row = {"cp": cp, "games": n, "accuracy": correct / args.iterations,
                   "false_pair_rate": false_pair / args.iterations, "mean_net_influence_AB": float(np.mean(gammas))}
            rows.append(row)
            print(f"{cp:.1f}  {n:5d}  {row['accuracy']:8.2f}  {row['false_pair_rate']:14.2f}  {row['mean_net_influence_AB']:.4f}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"alpha": args.alpha, "iterations": args.iterations, "seed": args.seed, "rows": rows}, indent=2))
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
