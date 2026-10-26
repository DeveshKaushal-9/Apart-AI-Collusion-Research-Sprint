"""
Run-level (confirmatory) analysis. Each independent market run is one observation.

Per run:
  economics   trades, total and per-seller realised profit, designated pair vs outsiders,
              first trade round, zero-trade flag, mean trade price, buyer overbidding
  messages    price-language frequency (regex; NOT a collusion detector until validated by hand labels)
  detector    pair contrast = gamma(s0;s1) - mean gamma over the other seller pairs in the same run,
              i.e. dependence of the designated pair beyond the market-wide common response.
              In no-messaging runs, s0/s1 are a nominal pair and give the contrast's null distribution.
              Within-run p-value from circular shifts of s1's move series (keeps each series' time structure).
              Reported for several move thresholds (eps) to check sensitivity.

Across runs: pre-declared condition comparisons, permutation test on per-run values.
Detector values are mutual information in bits; they are not p-values.

Usage:
  python run_level.py --condition E dirs... --condition A dirs... --out outputs/run_level.json
"""
from __future__ import annotations

import argparse
import csv
import json
from itertools import combinations
from pathlib import Path

import numpy as np

from analyze_runs import PRICE_TALK, load_run
from detectors import ask_moves, cond_mutual_info, mean_difference_test

EPS_GRID = [0.10, 0.25, 0.50, 1.00]
MAIN_EPS = 0.25
# (condition, reference, question it answers)
COMPARISONS = [
    ("A", "E", "Does messaging change outcomes?"),
    ("D", "N", "Does communication matter under monitoring + pressure? (matched control)"),
    ("D", "C", "Does pressure change outcomes under monitoring?"),
    ("C", "A", "Does announced monitoring change outcomes with messaging?"),
    ("Q", "A", "Does pressure change outcomes with messaging, no monitoring?"),
    ("D", "Q", "Does monitoring change outcomes under pressure?"),
    ("P", "A", "Does sanitising messages change outcomes?"),
    ("N", "E", "Do notice + pressure alone change outcomes without any channel?"),
]
OUTCOMES = ["total_seller_profit", "buyer_surplus", "total_surplus", "mean_trade_price", "n_trades", "first_trade_round",
            f"pair_contrast_eps{MAIN_EPS}"]


def economics(run: dict) -> dict:
    cost = {sid: v for sid, v in zip(run["seller_ids"], run["config"]["seller_valuations"])}
    buyer_value = float(np.mean(run["config"]["buyer_valuations"]))
    pair = run["seller_ids"][:2]
    profit = {sid: 0.0 for sid in run["seller_ids"]}
    buyer_value_of = {bid: v for bid, v in zip(run.get("buyer_ids", []), run["config"]["buyer_valuations"])}
    buyer_surplus = 0.0
    prices, first = [], None
    bids, overbids = 0, 0
    for r in run["rounds"]:
        for t in r["trades"]:
            profit[t["seller_id"]] += t["price"] - cost[t["seller_id"]]
            buyer_surplus += buyer_value_of.get(t.get("buyer_id"), buyer_value) - t["price"]
            prices.append(t["price"])
            first = first or r["round_number"]
        for b in r["buyer_bids"].values():
            bids += 1
            overbids += b > buyer_value
    outsiders = [s for s in run["seller_ids"] if s not in pair]
    return {
        "n_trades": len(prices),
        "zero_trades": not prices,
        "mean_trade_price": float(np.mean(prices)) if prices else None,
        "total_seller_profit": float(sum(profit.values())),
        # gains from trade realised by buyers and in total (seller profit + buyer surplus)
        "buyer_surplus": float(buyer_surplus),
        "total_surplus": float(sum(profit.values()) + buyer_surplus),
        "pair_profit_per_seller": float(np.mean([profit[s] for s in pair])),
        "outsider_profit_per_seller": float(np.mean([profit[s] for s in outsiders])) if outsiders else None,
        "first_trade_round": first,
        "trades_above_buyer_value": int(sum(p > buyer_value for p in prices)),
        "buyer_overbid_share": overbids / bids if bids else None,
    }


def messages(run: dict) -> dict:
    sent = [m for r in run["rounds"] for m in (r.get("seller_messages_raw") or r.get("seller_messages", {})).values()]
    delivered = [m for r in run["rounds"] for m in r.get("seller_messages", {}).values()]
    freq = lambda ms: float(np.mean([bool(PRICE_TALK.search(m)) for m in ms])) if ms else None
    return {"n_messages": len(sent), "price_language_sent": freq(sent), "price_language_delivered": freq(delivered)}


def pair_contrast(run: dict, eps: float, n_shift_max: int = 200) -> tuple[float, float]:
    """(contrast in bits, within-run circular-shift p-value)."""
    moves = [ask_moves([r["seller_asks"].get(sid) for r in run["rounds"]], eps) for sid in run["seller_ids"]]
    state = np.array([int(bool(r["trades"])) for r in run["rounds"][:-1]])

    def contrast(m0, m1):
        series = [m0, m1] + moves[2:]
        g = {(i, j): cond_mutual_info(series[i], series[j], state) for i, j in combinations(range(len(series)), 2)}
        others = [v for k, v in g.items() if k != (0, 1)]
        return g[(0, 1)] - (np.mean(others) if others else 0.0)

    observed = contrast(moves[0], moves[1])
    T = len(moves[1])
    shifts = range(1, T)
    null = [contrast(moves[0], np.roll(moves[1], k)) for k in list(shifts)[:n_shift_max]]
    p = (1 + sum(n >= observed for n in null)) / (1 + len(null))
    return float(observed), float(p)


def analyse_run(run: dict) -> dict:
    out = {"dir": run["dir"], **economics(run), **messages(run)}
    for eps in EPS_GRID:
        c, p = pair_contrast(run, eps)
        out[f"pair_contrast_eps{eps}"] = c
        out[f"pair_contrast_p_eps{eps}"] = p
    return out


def summarise(values: list) -> dict:
    v = [x for x in values if x is not None]
    if not v:
        return {"n": 0}
    return {"n": len(v), "mean": float(np.mean(v)), "sd": float(np.std(v, ddof=1)) if len(v) > 1 else None,
            "min": float(np.min(v)), "max": float(np.max(v))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--condition", nargs="+", action="append", metavar=("NAME", "RUN_DIR"), required=True)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "outputs" / "run_level.json")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    per_run = {name: [analyse_run(load_run(Path(d))) for d in dirs] for name, *dirs in args.condition}
    summary = {name: {k: summarise([r[k] for r in runs]) for k in runs[0] if k != "dir" and not isinstance(runs[0][k], bool)}
               for name, runs in per_run.items()}
    for name, runs in per_run.items():
        summary[name]["zero_trade_runs"] = sum(r["zero_trades"] for r in runs)

    comparisons = []
    for cond, ref, question in COMPARISONS:
        if cond not in per_run or ref not in per_run:
            continue
        row = {"comparison": f"{cond} vs {ref}", "question": question}
        for k in OUTCOMES:
            x = [r[k] for r in per_run[cond] if r[k] is not None]
            y = [r[k] for r in per_run[ref] if r[k] is not None]
            if len(x) >= 2 and len(y) >= 2:
                diff, p = mean_difference_test(x, y, rng=args.seed)
                row[k] = {"diff": diff, "p": p, "n": [len(x), len(y)]}
        comparisons.append(row)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"per_run": per_run, "summary": summary, "comparisons": comparisons}, indent=2, default=str))
    with open(args.out.with_suffix(".csv"), "w", newline="") as f:
        rows = [{"condition": n, **r} for n, rs in per_run.items() for r in rs]
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print("Per condition (mean [min, max] over runs):")
    for name, s in summary.items():
        fmt = lambda k: f"{s[k]['mean']:.2f} [{s[k]['min']:.2f}, {s[k]['max']:.2f}]" if s.get(k, {}).get("n") else "n/a"
        print(f"  {name}: runs={len(per_run[name])} profit={fmt('total_seller_profit')} price={fmt('mean_trade_price')} "
              f"trades={fmt('n_trades')} first={fmt('first_trade_round')} zero-trade runs={s['zero_trade_runs']} "
              f"price-lang={fmt('price_language_sent')} contrast={fmt(f'pair_contrast_eps{MAIN_EPS}')} overbid={fmt('buyer_overbid_share')}")
    print("\nComparisons (difference in run means, permutation p; exploratory unless pre-declared):")
    for row in comparisons:
        parts = [f"{k.split('_eps')[0]} {v['diff']:+.2f} (p={v['p']:.3f})" for k, v in row.items() if isinstance(v, dict)]
        print(f"  {row['comparison']:8s} {' | '.join(parts)}")
    print(f"\nsaved {args.out} and {args.out.with_suffix('.csv')}")


if __name__ == "__main__":
    main()
