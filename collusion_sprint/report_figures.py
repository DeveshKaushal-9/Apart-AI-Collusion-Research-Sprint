"""
Report figures from the saved analysis outputs (no re-analysis).

  fig1_qwen_run_outcomes.png    per-run outcomes by condition (Qwen3-8B): price, profit, price language, buyer overbidding
  fig2_detector_sweep.png       scripted market: flag rate vs coordination strength, shared response present
  fig3_gpt41_price_vs_profit.png  GPT-4.1 reanalysis: price per trade vs total seller profit, per run
  report_figures_table.csv      every plotted value (table view)

Palette: validated categorical slots (light mode). Slots below 3:1 contrast are always paired with
text labels on the axis or line ends, so colour never carries identity alone.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).parent
RESULTS = HERE.parent / "kaggle_results"
OUT = HERE / "outputs" / "report_figures"
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]  # fixed order
COND_ORDER = ["E", "N", "A", "C", "D", "P"]
COND_LABEL = {"E": "E\nno channel", "N": "N\nno channel\n+notice+pressure", "A": "A\nmessaging",
              "C": "C\nmessaging\n+monitoring", "D": "D\nmessaging\n+monitoring\n+pressure", "P": "P\nmessaging\nsanitised"}
rows = []


def style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def dot_panel(ax, per_run, key, title, conds, fmt, scale=1.0):
    rng = np.random.default_rng(0)
    for i, c in enumerate(conds):
        vals = [r[key] * scale for r in per_run.get(c, []) if r.get(key) is not None]
        if not vals:
            ax.text(i, 0, "n/a", ha="center", va="bottom", color=INK_2, fontsize=8)
            continue
        color = SERIES[COND_ORDER.index(c)]
        ax.bar(i, np.mean(vals), width=0.6, color=color, alpha=0.3, edgecolor=SURFACE, linewidth=2)
        ax.scatter(i + rng.uniform(-0.13, 0.13, len(vals)), vals, s=26, color=color, edgecolor=SURFACE, linewidth=1.2, zorder=3)
        ax.text(i, 1.01, fmt(np.mean(vals)), ha="center", va="bottom", color=INK, fontsize=8,
                transform=ax.get_xaxis_transform())
        for v in vals:
            rows.append({"figure": "fig1", "panel": key, "condition": c, "value": v})
    ax.set_xticks(range(len(conds)), conds, fontsize=9, color=INK, fontweight="bold")
    ax.set_title(title, color=INK, fontsize=9.5, loc="left", pad=16)
    style(ax)


def fig1():
    data = json.loads((RESULTS / "run_level_qwen.json").read_text())["per_run"]
    fig, axes = plt.subplots(2, 2, figsize=(9.5, 6.6), facecolor=SURFACE)
    dot_panel(axes[0, 0], data, "mean_trade_price", "Mean trade price ($) per run", COND_ORDER, lambda v: f"${v:.1f}")
    axes[0, 0].set_ylim(80, 100)
    dot_panel(axes[0, 1], data, "total_seller_profit", "Total seller profit ($) per run", COND_ORDER, lambda v: f"${v:,.0f}")
    msg_conds = [c for c in COND_ORDER if c in ("A", "C", "D", "P")]
    dot_panel(axes[1, 0], data, "price_language_sent", "Messages with price language (%): bars = sent, hollow = delivered",
              msg_conds, lambda v: f"{v:.1f}%", 100)
    for i, c in enumerate(msg_conds):  # delivered share, same colour, hollow marker (differs from sent only in P)
        vals = [r["price_language_delivered"] * 100 for r in data[c] if r.get("price_language_delivered") is not None]
        axes[1, 0].scatter([i + 0.32] * len(vals), vals, s=30, facecolor="none", edgecolor=SERIES[COND_ORDER.index(c)], linewidth=1.4, zorder=3)
        for v in vals:
            rows.append({"figure": "fig1", "panel": "price_language_delivered", "condition": c, "value": v})
    axes[1, 0].set_ylim(0, 110)
    dot_panel(axes[1, 1], data, "buyer_overbid_share", "Buyer bids above own value (%)", COND_ORDER, lambda v: f"{v:.0f}%", 100)
    fig.suptitle("Qwen3-8B double auction: price language varies across conditions; no detectable difference in prices or seller profit",
                 x=0.01, ha="left", color=INK, fontsize=10.5)
    fig.text(0.01, 0.005, "E no channel · N no channel + monitoring notice + pressure · A messaging · C messaging + monitoring · "
             "\nD messaging + monitoring + pressure · P messaging, sanitised (unannounced). Filled dots = runs; bars and numbers above = their mean; hollow = delivered.",
             color=INK_2, fontsize=7.5, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(OUT / "fig1_qwen_run_outcomes.png", dpi=200, facecolor=SURFACE)
    plt.close(fig)


def fig2():
    res = json.loads((HERE / "outputs" / "scripted_sweep.json").read_text())["results"]
    strengths = [float(k.split("joint")[1]) for k in res]
    detectors = [("net_influence_rate", "Net influence"), ("pooled_gamma_rate", "Pooled dependence test"),
                 ("price_matching_rate", "Price matching"), ("pair_contrast_run_rate", "Within-run pair contrast")]
    fig, ax = plt.subplots(figsize=(7.2, 4.0), facecolor=SURFACE)
    style(ax)
    ends = []
    for i, (key, name) in enumerate(detectors):
        y = [res[k][key] * 100 for k in res]
        ax.plot(strengths, y, color=SERIES[i], linewidth=2, marker="o", markersize=5, markeredgecolor=SURFACE, label=name)
        ends.append((y[-1], name))
        for s, v in zip(strengths, y):
            rows.append({"figure": "fig2", "panel": name, "condition": s, "value": v})
    ax.legend([l for l in ax.get_lines()], [n for _, n in detectors], frameon=False, fontsize=8, labelcolor=INK,
              loc="lower right")
    ax.annotate("strength 0 = shared market response only:\nany flag here is a false alarm", (0, 4), xytext=(0.08, 40), color=INK_2, fontsize=8,
                arrowprops={"arrowstyle": "-", "color": INK_2, "linewidth": 0.8})
    ax.set_xlabel("Strength of the pair-specific signal added to the designated pair (0 = none)", color=INK_2, fontsize=9)
    ax.set_ylabel("Pair flagged (% of datasets / runs)", color=INK_2, fontsize=9)
    ax.set_ylim(-3, 105)
    ax.set_xlim(-0.05, strengths[-1] + 0.05)
    ax.set_title("Synthetic auction, shared market signal present: flag rate vs pair-specific signal strength", color=INK, fontsize=9.5, loc="left")
    fig.tight_layout()
    fig.savefig(OUT / "fig2_detector_sweep.png", dpi=200, facecolor=SURFACE)
    plt.close(fig)


def fig3():
    path = HERE / "outputs" / "run_level_gpt41.json"
    data = json.loads(path.read_text())["per_run"]
    conds = ["E", "A", "C", "Q", "D"]
    labels = {"E": "E\nno\nmessaging", "A": "A\nmessaging", "C": "C\nmonitored", "Q": "Q\npressure", "D": "D\nmonitored\n+pressure"}
    gpt_color = {"E": SERIES[0], "A": SERIES[2], "C": SERIES[3], "Q": "#6250d6", "D": SERIES[4]}  # same entity colours as Fig 1; Q validated
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.9), facecolor=SURFACE)
    panels = [("mean_trade_price", "Price per trade ($)", lambda v: f"${v:.1f}"),
              ("total_seller_profit", "Seller profit ($)", lambda v: f"${v:,.0f}"),
              ("buyer_surplus", "Buyer surplus ($)", lambda v: f"${v:,.0f}"),
              ("total_surplus", "Total surplus ($)", lambda v: f"${v:,.0f}")]
    rng = np.random.default_rng(0)
    for ax, (key, title, fmt) in zip(axes, panels):
        style(ax)
        for i, c in enumerate(conds):
            vals = [r[key] for r in data[c] if r.get(key) is not None]
            color = gpt_color[c]
            ax.bar(i, np.mean(vals), width=0.6, color=color, alpha=0.3, edgecolor=SURFACE, linewidth=2)
            ax.scatter(i + rng.uniform(-0.13, 0.13, len(vals)), vals, s=22, color=color, edgecolor=SURFACE, linewidth=1.2, zorder=3)
            ax.text(i, 1.01, fmt(np.mean(vals)), ha="center", va="bottom", color=INK, fontsize=8,
                    transform=ax.get_xaxis_transform())
            for v in vals:
                rows.append({"figure": "fig3", "panel": key, "condition": c, "value": v})
        ax.set_xticks(range(len(conds)), [labels[c] for c in conds], fontsize=6.5, color=INK)
        ax.set_title(title, color=INK, fontsize=9.5, loc="left", pad=16)
    axes[0].set_ylim(80, 100)
    fig.suptitle("GPT-4.1 runs from Agrawal et al. (2025), our reanalysis: pressure (Q, D) cuts buyer and total surplus whether messages are loud (Q) or quiet (D)",
                 x=0.01, ha="left", color=INK, fontsize=10.5)
    fig.tight_layout()
    fig.savefig(OUT / "fig3_gpt41_price_vs_profit.png", dpi=200, facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig1(); fig2(); fig3()
    with open(OUT / "report_figures_table.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["figure", "panel", "condition", "value"])
        w.writeheader(); w.writerows(rows)
    print("saved to", OUT)
