"""
Layer 1 — the acuity scorer. Recommends; never decides.

Gradient-boosted trees with native NaN handling, so missingness reaches the model
intact rather than being papered over by an imputer. Every score leaves this
layer with a confidence attached: a bare number is not an acceptable output, and
the brief says so explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

from contracts.schema import Dataset
from layer1 import features


@dataclass
class Scored:
    """A Layer 1 output. There is no way to get the risk without the confidence."""

    risk: float
    band: int                 # 1 (most urgent) .. 5
    confidence: str           # HIGH | MODERATE | LOW
    reasons: tuple[str, ...]
    missing: tuple[str, ...]

    def as_dict(self) -> dict:
        return dict(risk=round(self.risk, 4), band=self.band,
                    confidence=self.confidence, reasons=list(self.reasons),
                    missing=list(self.missing))


class AcuityScorer:
    def __init__(self, sensitivity_target: float = 0.95):
        self.sensitivity_target = sensitivity_target
        self.model: HistGradientBoostingClassifier | None = None
        self.columns: list[str] = []
        self.threshold: float = 0.5
        self.band_cuts: list[float] = []
        self.metrics: dict = {}

    # --- fitting -----------------------------------------------------------

    def fit(self, ds: Dataset, *, seed: int = 0) -> "AcuityScorer":
        ds.require_trainable()          # refuses Isfahan, loudly
        X = features.build(ds)
        y = features.critical_outcome(ds).reindex(X.index).fillna(0).astype(int)

        stratify = y if y.nunique() > 1 and y.value_counts().min() >= 2 else None
        Xtr, Xte, ytr, yte = train_test_split(
            X, y, test_size=0.3, random_state=seed, stratify=stratify)

        self.columns = list(X.columns)
        self.model = HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.08, max_depth=6,
            early_stopping=False, random_state=seed)
        self.model.fit(Xtr, ytr)

        p = self.model.predict_proba(Xte)[:, 1]
        self.metrics = {
            "n_train": len(Xtr), "n_test": len(Xte),
            "prevalence": round(float(y.mean()), 4),
            "auc": round(float(roc_auc_score(yte, p)), 4) if yte.nunique() > 1 else None,
        }
        self.threshold = self._operating_point(yte.to_numpy(), p)
        self.metrics["threshold"] = round(self.threshold, 4)
        self.metrics.update(self._at_threshold(yte.to_numpy(), p))

        # Bands come from where a patient sits in the risk distribution, not from
        # the review threshold. Tying them together collapses everyone into band 1
        # whenever the operating point is aggressive — which, tuned to 95%
        # sensitivity on a weak signal, it always is.
        train_p = self.model.predict_proba(Xtr)[:, 1]
        self.band_cuts = [float(np.quantile(train_p, q)) for q in (0.98, 0.90, 0.65, 0.30)]
        self.metrics["band_cuts"] = [round(c, 4) for c in self.band_cuts]
        return self

    def _operating_point(self, y: np.ndarray, p: np.ndarray) -> float:
        """
        Tune to the sensitivity target rather than to accuracy.

        ACS sets <=5% undertriage as the field standard, so we take the highest
        threshold that still catches 95% of critical patients and report the
        specificity we paid for it.
        """
        if y.sum() == 0:
            return 0.5
        pos = np.sort(p[y == 1])
        idx = int(np.floor((1 - self.sensitivity_target) * len(pos)))
        return float(pos[min(idx, len(pos) - 1)])

    def _at_threshold(self, y: np.ndarray, p: np.ndarray) -> dict:
        pred = p >= self.threshold
        tp, fn = int((pred & (y == 1)).sum()), int((~pred & (y == 1)).sum())
        tn, fp = int((~pred & (y == 0)).sum()), int((pred & (y == 0)).sum())
        sens = tp / (tp + fn) if tp + fn else float("nan")
        spec = tn / (tn + fp) if tn + fp else float("nan")
        return {"sensitivity": round(sens, 4), "specificity": round(spec, 4),
                "undertriage_rate": round(1 - sens, 4)}

    # --- scoring -----------------------------------------------------------

    def score_frame(self, X: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("scorer is not fitted")
        return self.model.predict_proba(X.reindex(columns=self.columns))[:, 1]

    def score_one(self, row: dict) -> Scored:
        """Score a single patient dict, as the live service does."""
        X = pd.DataFrame([row]).reindex(columns=self.columns)
        risk = float(self.score_frame(X)[0])
        missing = tuple(c for c in ("o2sat", "sbp", "heartrate", "resprate", "temperature")
                        if row.get(c) is None or pd.isna(row.get(c)))
        return Scored(
            risk=risk,
            band=self.band_for(risk),
            confidence=self.confidence_for(risk, len(missing)),
            reasons=self.reasons_for(row, risk),
            missing=missing,
        )

    def band_for(self, risk: float) -> int:
        """Band by position in the training risk distribution (1 = most urgent)."""
        for band, cut in enumerate(self.band_cuts, start=1):
            if risk >= cut:
                return band
        return 5

    def flags_for_review(self, risk: float) -> bool:
        """The operating point: tuned to 95% sensitivity, separate from banding."""
        return risk >= self.threshold

    def confidence_for(self, risk: float, n_missing: int) -> str:
        """
        A provisional confidence. Day 2 replaces this with Mondrian conformal
        prediction sets, which give a real coverage guarantee on the critical
        class rather than a heuristic.
        """
        if n_missing >= 3:
            return "LOW"
        if n_missing >= 1:
            return "MODERATE"
        if not self.band_cuts:
            return "MODERATE"
        # confident when the risk sits clear of the nearest band boundary
        nearest = min(abs(risk - c) for c in self.band_cuts)
        spread = max(self.band_cuts) - min(self.band_cuts) or 1.0
        return "HIGH" if nearest > 0.15 * spread else "MODERATE"

    @staticmethod
    def reasons_for(row: dict, risk: float) -> tuple[str, ...]:
        """Plain-language reasons. Day 2 swaps the heuristics for SHAP."""
        out = []
        hr, sbp, o2 = row.get("heartrate"), row.get("sbp"), row.get("o2sat")
        if hr and sbp and sbp > 0 and hr / sbp >= 0.9:
            out.append(f"shock index {hr / sbp:.2f}")
        if o2 is not None and not pd.isna(o2) and o2 < 94:
            out.append(f"SpO2 {int(o2)}%")
        if sbp is not None and not pd.isna(sbp) and sbp < 100:
            out.append(f"SBP {int(sbp)}")
        if row.get("is_paediatric"):
            out.append("paediatric weighting")
        if row.get("is_geriatric"):
            out.append("geriatric weighting")
        return tuple(out[:3]) or (f"composite risk {risk:.2f}",)
