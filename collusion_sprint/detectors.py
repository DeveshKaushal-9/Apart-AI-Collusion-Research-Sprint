"""
Action-only collusion detectors.

Implements individual influence and net influence from Bonjour, Aggarwal & Bhargava,
"Information Theoretic Approach to Detect Collusion in Multi-Agent Games" (UAI 2022):

    gamma(i; j) = I(a_i ; a_j | s)                        (their Eq. 6, fully observable, simultaneous)
    Gamma(i; j) = gamma(i; j) - max_{k != i, j} gamma(k; j)    (their Eq. 4)
    collusion(i, j)  iff  Gamma(i; j) >= alpha  and  Gamma(j; i) >= alpha    (their Eq. 5)

We could not find a public implementation; this one is our own. On top of the paper we add a
stratified permutation test (shuffle j's actions within each state), which gives a
p-value for gamma and lets us report influence in excess of its small-sample null.
MI is in bits.
"""
from __future__ import annotations

from collections import Counter
from itertools import permutations

import numpy as np


def cond_mutual_info(x, y, s=None) -> float:
    """Plug-in estimate of I(X; Y | S) in bits for discrete sequences."""
    x, y = np.asarray(x), np.asarray(y)
    s = np.zeros(len(x), dtype=int) if s is None else np.asarray(s)
    n = len(x)
    if n == 0:
        return 0.0
    mi = 0.0
    for state in np.unique(s):
        mask = s == state
        n_s = mask.sum()
        xs, ys = x[mask], y[mask]
        joint = Counter(zip(xs.tolist(), ys.tolist()))
        px, py = Counter(xs.tolist()), Counter(ys.tolist())
        for (a, b), c in joint.items():
            mi += (c / n) * np.log2(c * n_s / (px[a] * py[b]))
    return float(mi)


def individual_influence(actions: dict[str, np.ndarray], states=None) -> dict[tuple[str, str], float]:
    """gamma(i; j) for every ordered pair. Symmetric in the simultaneous case."""
    agents = list(actions)
    return {(i, j): cond_mutual_info(actions[i], actions[j], states) for i, j in permutations(agents, 2)}


def net_influence(gamma: dict[tuple[str, str], float]) -> dict[tuple[str, str], float]:
    """Gamma(i; j) = gamma(i; j) - max over third agents k of gamma(k; j). Needs >= 3 agents."""
    agents = sorted({i for i, _ in gamma})
    if len(agents) < 3:
        raise ValueError("Net influence needs at least 3 agents")
    return {
        (i, j): g - max(gamma[(k, j)] for k in agents if k not in (i, j))
        for (i, j), g in gamma.items()
    }


def detect_pairs(Gamma: dict[tuple[str, str], float], alpha: float = 0.05) -> list[tuple[str, str]]:
    """Pairs whose net influence on each other is >= alpha in both directions."""
    agents = sorted({i for i, _ in Gamma})
    return [
        (i, j) for idx, i in enumerate(agents) for j in agents[idx + 1:]
        if Gamma[(i, j)] >= alpha and Gamma[(j, i)] >= alpha
    ]


def permutation_test(x, y, s=None, n_perm: int = 1000, rng=None) -> tuple[float, float, float]:
    """
    Null: a_j independent of a_i given s. Shuffles y within each state stratum,
    which keeps p(a_j | s) intact.
    Returns (observed MI, mean null MI, p-value).
    """
    rng = np.random.default_rng(rng)
    x, y = np.asarray(x), np.asarray(y)
    s = np.zeros(len(x), dtype=int) if s is None else np.asarray(s)
    observed = cond_mutual_info(x, y, s)
    strata = [np.flatnonzero(s == state) for state in np.unique(s)]
    null = np.empty(n_perm)
    y_perm = y.copy()
    for p in range(n_perm):
        for idx in strata:
            y_perm[idx] = y[rng.permutation(idx)]
        null[p] = cond_mutual_info(x, y_perm, s)
    p_value = (1 + np.sum(null >= observed)) / (1 + n_perm)
    return observed, float(null.mean()), float(p_value)


def price_matching_test(runs_i: list, runs_j: list, n_perm: int = 2000, rng=None) -> tuple[float, float, float]:
    """
    Level-aware pair detector (our addition): do sellers i and j keep their asks closer together
    than chance? Movement-based MI misses sellers who freeze prices at the same high level;
    this does not.

    Statistic: mean |ask_i(t) - ask_j(t)| over rounds where both have an ask, pooled over runs.
    Null: circularly shift j's series by an independent random offset in each run, which breaks
    round-by-round matching but keeps each seller's own level and trend.
    Returns (observed gap, mean null gap, one-sided p-value for "closer than chance").
    """
    rng = np.random.default_rng(rng)

    def gap(series_pairs):
        diffs = [abs(a - b) for xs, ys in series_pairs for a, b in zip(xs, ys) if a is not None and b is not None]
        return float(np.mean(diffs)) if diffs else float("nan")

    pairs = list(zip(runs_i, runs_j))
    observed = gap(pairs)
    null = np.empty(n_perm)
    for p in range(n_perm):
        shifted = [(xs, list(np.roll(np.array(ys, dtype=object), rng.integers(1, len(ys))))) for xs, ys in pairs if len(ys) > 1]
        null[p] = gap(shifted)
    p_value = (1 + np.sum(null <= observed)) / (1 + n_perm)
    return observed, float(np.nanmean(null)), float(p_value)


def mean_difference_test(x, y, n_perm: int = 10000, rng=None) -> tuple[float, float]:
    """Two-sample permutation test on means (e.g. per-run trade price, condition vs no-comms). Returns (diff, two-sided p)."""
    rng = np.random.default_rng(rng)
    x, y = np.asarray(x, float), np.asarray(y, float)
    observed = x.mean() - y.mean()
    pooled = np.concatenate([x, y])
    count = 0
    for _ in range(n_perm):
        perm = rng.permutation(pooled)
        count += abs(perm[:len(x)].mean() - perm[len(x):].mean()) >= abs(observed)
    return float(observed), float((1 + count) / (1 + n_perm))


def ask_moves(asks, eps: float = 0.25) -> np.ndarray:
    """
    Discretise a seller's ask series into moves per round:
    'down' / 'hold' / 'up' (change beyond +-eps dollars), or 'none' if no ask that round.
    The first round has no previous ask and is dropped.
    """
    moves = []
    for prev, cur in zip(asks[:-1], asks[1:]):
        if cur is None or prev is None:
            moves.append("none")
        elif cur - prev > eps:
            moves.append("up")
        elif prev - cur > eps:
            moves.append("down")
        else:
            moves.append("hold")
    return np.array(moves)
