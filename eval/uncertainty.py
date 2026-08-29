"""
How much of a difference is real, and how much is the sample size?

Two of this project's stated limitations were really the same complaint: a
number was reported as a point estimate when the sample behind it was small
enough that the point estimate was the least interesting thing about it. A 5%
fairness gap measured on 375 patients and a 5% gap measured on 300,000 are not
the same finding, and reporting them the same way is the sort of thing that
survives right up until someone asks.

Nothing here makes a result better. It makes the result honest about its own
width, which sometimes means admitting the effect cannot be resolved at all.
"""
from __future__ import annotations

import numpy as np
from scipy import stats


def clopper_pearson(successes: int, n: int, confidence: float = 0.95
                    ) -> tuple[float, float]:
    """
    Exact binomial interval for a rate.

    Exact rather than normal-approximation because these rates sit near 1.0 —
    a sensitivity of 96% on 79 patients has a Wald interval that runs past 100%,
    which is not a thing sensitivity can do.
    """
    if n == 0:
        return (float("nan"), float("nan"))
    alpha = 1 - confidence
    lo = stats.beta.ppf(alpha / 2, successes, n - successes + 1) if successes > 0 else 0.0
    hi = (stats.beta.ppf(1 - alpha / 2, successes + 1, n - successes)
          if successes < n else 1.0)
    return (float(lo), float(hi))


def rate_with_ci(flags: np.ndarray, confidence: float = 0.95) -> dict:
    """A rate, its interval, and the n it rests on — reported together."""
    n = int(len(flags))
    k = int(np.sum(flags))
    lo, hi = clopper_pearson(k, n, confidence)
    return {"rate": round(k / n, 4) if n else None, "n": n,
            "ci_low": round(lo, 4), "ci_high": round(hi, 4),
            "ci_width": round(hi - lo, 4) if n else None}


def bootstrap(values: np.ndarray, statistic=np.median, *, n_boot: int = 5000,
              confidence: float = 0.95, seed: int = 3) -> dict:
    """
    Percentile bootstrap for a statistic with no closed form — a median lead
    time, or the gap between two subgroup rates.
    """
    values = np.asarray(values)
    values = values[~np.isnan(values)] if values.dtype.kind == "f" else values
    if len(values) == 0:
        return {"estimate": None, "ci_low": None, "ci_high": None, "n": 0}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(n_boot, len(values)))
    draws = statistic(values[idx], axis=1)
    lo, hi = np.percentile(draws, [(1 - confidence) / 2 * 100,
                                   (1 + confidence) / 2 * 100])
    return {"estimate": round(float(statistic(values)), 2),
            "ci_low": round(float(lo), 2), "ci_high": round(float(hi), 2),
            "n": int(len(values))}


def wilson(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval — well behaved at 0 and 1, unlike the Wald form."""
    if n == 0:
        return (float("nan"), float("nan"))
    z = stats.norm.ppf(1 - (1 - confidence) / 2)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (float(max(0.0, centre - half)), float(min(1.0, centre + half)))


def gap_with_ci(flags_a: np.ndarray, flags_b: np.ndarray,
                confidence: float = 0.95, **_ignored) -> dict:
    """
    The difference between two rates, with an interval (Newcombe's method).

    An interval that contains zero means the two groups cannot be told apart at
    this sample size. That is the answer, and it is a different answer from "the
    gap is small".

    Not a bootstrap. Resampling a rate collapses at the boundary: with two
    patients who were both flagged, every resample is those same two patients,
    so the bootstrap reports a *zero-width* interval and declares a difference
    from a 300,000-patient group to be real. That is the exact case this
    function exists to catch. Newcombe combines the two Wilson score intervals
    instead, which stays sane at 0 and 1 and costs no memory — the resampling
    version also had to allocate n_boot x n floats and was OOM-killed on a
    300,000-patient subgroup.
    """
    a, b = np.asarray(flags_a, dtype=float), np.asarray(flags_b, dtype=float)
    if len(a) == 0 or len(b) == 0:
        return {"gap": None, "ci_low": None, "ci_high": None,
                "distinguishable": None}

    ka, na = int(a.sum()), len(a)
    kb, nb = int(b.sum()), len(b)
    pa, pb = ka / na, kb / nb
    la, ua = wilson(ka, na, confidence)
    lb, ub = wilson(kb, nb, confidence)

    lo = (pa - pb) - np.sqrt((pa - la) ** 2 + (ub - pb) ** 2)
    hi = (pa - pb) + np.sqrt((ua - pa) ** 2 + (pb - lb) ** 2)
    return {"gap": round(pa - pb, 4),
            "ci_low": round(float(lo), 4), "ci_high": round(float(hi), 4),
            "n_a": na, "n_b": nb,
            # Does the interval exclude zero? If not, the gap is not resolvable
            # here however large the point estimate looks.
            "distinguishable": bool(lo > 0 or hi < 0)}


def conformal_quantile_index(n: int, alpha: float) -> int:
    """
    The finite-sample conformal index: ceil((n+1)(1-alpha)) - 1.

    The naive `floor(alpha * n)` differs from this by at most one order
    statistic, and on many group sizes not at all — so it is a correctness fix,
    not an explanation for any particular gap. The finite-sample form is the one
    that carries the coverage guarantee, which matters most exactly where the
    groups are smallest and a single order statistic is worth whole percentage
    points of sensitivity.
    """
    if n <= 0:
        return 0
    k = int(np.ceil((n + 1) * (1 - alpha))) - 1
    return int(np.clip(n - 1 - k, 0, n - 1))
