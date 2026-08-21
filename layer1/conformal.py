"""
Mondrian (class-conditional) conformal prediction.

The brief requires that no score is returned without a confidence indicator.
Conformal prediction answers that properly — with one trap worth naming in the
pitch.

Standard *marginal* conformal guarantees average coverage across all patients.
On imbalanced data it hits that average by badly under-covering the rare class,
which here is precisely the critical patients we cannot afford to miss. Mondrian
conformal calibrates separately per class, so the guarantee lands *on the
critical class specifically*.

The taxonomy is arbitrary, not just the label. Calibrating on class x subgroup
gives a per-subgroup coverage guarantee — a mathematical answer to the Obermeyer
problem rather than a policy promise. See `fit(groups=...)`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PredictionSet:
    """
    The set of labels that cannot be ruled out at the chosen confidence level.

    {1}     confidently critical
    {0}     confidently non-critical
    {0,1}   genuinely uncertain — the honest answer, and the one that should
            pull a human in rather than being collapsed to a number
    {}      unlike anything in calibration; treat as out-of-distribution and
            escalate, never dismiss
    """

    labels: frozenset[int]
    alpha: float
    group: str = "all"

    @property
    def is_certain(self) -> bool:
        return len(self.labels) == 1

    @property
    def is_empty(self) -> bool:
        return len(self.labels) == 0

    @property
    def confidence(self) -> str:
        if self.is_empty:
            return "LOW"           # out of distribution — never call this HIGH
        if self.labels == {1}:
            return "HIGH"
        if self.labels == {0}:
            return "HIGH"
        return "MODERATE"

    def as_dict(self) -> dict:
        return dict(labels=sorted(self.labels), coverage=round(1 - self.alpha, 3),
                    group=self.group, confidence=self.confidence)


class MondrianConformal:
    """Class-conditional (optionally subgroup-conditional) conformal calibration."""

    def __init__(self, alpha: float = 0.05):
        self.alpha = alpha
        self.quantiles: dict[tuple, float] = {}
        self.classes: tuple[int, ...] = (0, 1)
        self.coverage: dict[str, float] = {}

    # --- calibration -------------------------------------------------------

    def fit(self, probs: np.ndarray, y: np.ndarray, groups: np.ndarray | None = None
            ) -> "MondrianConformal":
        """
        `probs` are calibrated P(critical); `y` the true labels; `groups` an
        optional taxonomy (sex, age band, race...) for subgroup-conditional
        guarantees.
        """
        y = np.asarray(y).astype(int)
        groups = np.array(["all"] * len(y)) if groups is None else np.asarray(groups).astype(str)
        p1 = np.asarray(probs, dtype=float)
        scores = {0: 1 - (1 - p1), 1: 1 - p1}       # nonconformity per candidate label

        for g in np.unique(groups):
            for k in self.classes:
                mask = (groups == g) & (y == k)
                n = int(mask.sum())
                if n == 0:
                    continue
                # finite-sample corrected quantile — the (1-alpha)(n+1)/n order statistic
                level = min(1.0, np.ceil((n + 1) * (1 - self.alpha)) / n)
                self.quantiles[(g, k)] = float(np.quantile(scores[k][mask], level))

        self._measure_coverage(p1, y, groups)
        return self

    def _measure_coverage(self, p1: np.ndarray, y: np.ndarray, groups: np.ndarray) -> None:
        """Empirical coverage per class. Report it; a guarantee unverified is a claim."""
        for k in self.classes:
            mask = y == k
            if not mask.any():
                continue
            covered = [k in self.predict(p, group=g).labels
                       for p, g in zip(p1[mask], groups[mask])]
            self.coverage[f"class_{k}"] = round(float(np.mean(covered)), 4)

    # --- prediction --------------------------------------------------------

    def predict(self, p1: float, group: str = "all") -> PredictionSet:
        labels = set()
        for k in self.classes:
            q = self.quantiles.get((group, k), self.quantiles.get(("all", k)))
            if q is None:
                continue
            score = (1 - p1) if k == 1 else p1
            if score <= q:
                labels.add(k)
        return PredictionSet(frozenset(labels), self.alpha, group)
