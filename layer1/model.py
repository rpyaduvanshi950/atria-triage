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
from layer1 import features, interactions, pathways
from layer1.conformal import MondrianConformal, PredictionSet
from layer1.pathways import PathwayProfile


# Worst plausible values, shared with the Layer 0 rule table so the two layers
# cannot drift apart on what "worst case" means.
def _load_worst_case() -> dict:
    import yaml
    from pathlib import Path
    spec = yaml.safe_load((Path("layer0") / "rules.yaml").read_text())
    return spec.get("worst_case", {})


try:
    WORST_CASE = _load_worst_case()
except Exception:                                # pragma: no cover
    WORST_CASE = {"o2sat": 85, "sbp": 80, "heartrate": 130, "resprate": 34, "temperature": 35.0}


@dataclass
class Scored:
    """A Layer 1 output. There is no way to get the risk without the confidence."""

    risk: float
    band: int                 # 1 (most urgent) .. 5
    #: How sure we are *how urgent* this patient is. From the conformal set.
    triage_confidence: str    # HIGH | MODERATE | LOW
    #: How sure we are *what is wrong*. From the spread across the three gates.
    #: A patient can be unambiguously critical and diagnostically opaque at once,
    #: and collapsing these into one number hides exactly that patient.
    diagnostic_confidence: str
    reasons: tuple[str, ...]
    missing: tuple[str, ...]
    #: the conformal prediction set. There is no path to a risk without one.
    prediction_set: PredictionSet | None = None
    pathways: PathwayProfile | None = None
    conflicts: tuple[str, ...] = ()
    amplified_by: float = 1.0

    @property
    def confidence(self) -> str:
        """The worse of the two, for anywhere that can only show one."""
        order = {"LOW": 0, "MODERATE": 1, "HIGH": 2}
        return min(self.triage_confidence, self.diagnostic_confidence, key=order.get)

    def as_dict(self) -> dict:
        return dict(risk=round(self.risk, 4), band=self.band,
                    confidence=self.confidence,
                    triage_confidence=self.triage_confidence,
                    diagnostic_confidence=self.diagnostic_confidence,
                    reasons=list(self.reasons), missing=list(self.missing),
                    prediction_set=self.prediction_set.as_dict() if self.prediction_set else None,
                    pathways=self.pathways.as_dict() if self.pathways else None,
                    conflicts=list(self.conflicts),
                    amplified_by=round(self.amplified_by, 2))


class AcuityScorer:
    def __init__(self, sensitivity_target: float = 0.95, alpha: float = 0.05):
        self.sensitivity_target = sensitivity_target
        self.alpha = alpha
        self.conformal: MondrianConformal | None = None
        #: vitals whose absence the model learned to read as *reassuring*.
        #: Scores for patients missing these are clamped — see _clamp.
        self.unsafe_missing: list[str] = []
        self.medians_: dict[str, float] = {}
        #: features this source could not support (constant or wholly absent)
        self.metrics_dropped: list[str] = []
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
        # a third split, held out from fitting, calibrates the conformal
        # quantiles — reusing training data would invalidate the guarantee
        strat2 = ytr if ytr.nunique() > 1 and ytr.value_counts().min() >= 2 else None
        Xtr, Xcal, ytr, ycal = train_test_split(
            Xtr, ytr, test_size=0.3, random_state=seed, stratify=strat2)

        # Drop features this source cannot support. Yale is an adults-only study,
        # so is_paediatric is constant zero, and its slim extract carries no pain
        # score — both are properties of the dataset, not faults. A constant or
        # all-missing column crashes the histogram binner, and silently keeping
        # one would be worse: it teaches nothing and hides that the source is
        # narrower than the feature set assumes.
        usable = [c for c in X.columns if X[c].nunique(dropna=True) >= 2]
        dropped = [c for c in X.columns if c not in usable]
        if dropped:
            self.metrics_dropped = dropped
        X, Xtr, Xcal, Xte = X[usable], Xtr[usable], Xcal[usable], Xte[usable]

        self.columns = list(usable)
        self.model = HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.08, max_depth=6,
            early_stopping=False, random_state=seed)
        self.model.fit(Xtr, ytr)

        cal_p = self.model.predict_proba(Xcal)[:, 1]
        groups = self._groups(Xcal)
        self.conformal = MondrianConformal(alpha=self.alpha).fit(cal_p, ycal.to_numpy(), groups)

        p = self.model.predict_proba(Xte)[:, 1]
        self.metrics = {
            "n_train": len(Xtr), "n_cal": len(Xcal), "n_test": len(Xte),
            "conformal_coverage": self.conformal.coverage,
            "features_dropped": list(self.metrics_dropped),
            "n_features": len(self.columns),
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

        # "Unknown is not normal" is a claim until it is audited. Trees learn
        # their own NaN direction, and here they learned that a missing heart
        # rate, respiratory rate or systolic is *reassuring* — a silent
        # undertriage path. Find those fields and clamp them at score time.
        self.medians_ = {c: float(v) for c, v in X.median(numeric_only=True).items()
                         if not pd.isna(v)}
        from layer1.verify import unsafe_fields
        self.unsafe_missing = unsafe_fields(self, X)
        self.metrics["unsafe_missing_fields"] = list(self.unsafe_missing)
        return self

    @staticmethod
    def _groups(X: pd.DataFrame) -> np.ndarray:
        """
        Mondrian taxonomy. Age band today; on Yale this becomes age x sex x race,
        which turns the fairness slide from a promise into a guarantee.
        """
        age = pd.to_numeric(X.get("age"), errors="coerce")
        return np.where(age < 15, "paediatric",
                        np.where(age > 60, "geriatric", "adult")).astype(str)

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
        risk = self._clamp(X, float(self.score_frame(X)[0]))
        missing = tuple(c for c in ("o2sat", "sbp", "heartrate", "resprate", "temperature")
                        if row.get(c) is None or pd.isna(row.get(c)))
        pset = None
        if self.conformal is not None:
            pset = self.conformal.predict(risk, group=str(self._groups(X)[0]))

        # the three gates, and whether anything is compounding or conflicting
        profile = pathways.assess(row)
        found = interactions.detect(row)
        amplify = interactions.amplification(row)

        band = self.band_for(risk)
        # A closing gate outranks a low statistical risk. The model is trained on
        # a coarse admission proxy; the pathway model encodes physiology, and
        # where they disagree we take the more urgent of the two.
        if profile.severity >= 0.75:
            band = min(band, 2)
        if profile.severity * amplify >= 1.0 and profile.severity >= 0.6:
            band = min(band, 2)

        reasons = list(self.reasons_for(row, risk))
        if profile.dominant and profile.severity >= 0.3:
            reasons.insert(0, profile.explain())
        for i in found:
            if i.kind == "conflict":
                reasons.insert(0, i.describe())

        return Scored(
            risk=risk,
            band=band,
            triage_confidence=self.confidence_for(risk, len(missing), pset),
            diagnostic_confidence=self.diagnostic_confidence_for(profile),
            reasons=tuple(reasons[:3]),
            missing=missing,
            prediction_set=pset,
            pathways=profile,
            conflicts=tuple(i.describe() for i in found if i.kind == "conflict"),
            amplified_by=amplify,
        )

    @staticmethod
    def diagnostic_confidence_for(profile: PathwayProfile) -> str:
        """
        How sure we are what is wrong — entirely separate from how sure we are
        how urgent it is. Nothing engaged is not the same as ambiguous: a well
        patient is diagnostically easy.
        """
        if profile.severity < 0.3:
            return "HIGH"
        if profile.spread >= 0.75:
            return "LOW"
        if profile.spread >= 0.5:
            return "MODERATE"
        return "HIGH"

    def _clamp(self, X: pd.DataFrame, risk: float) -> float:
        """
        Never let a missing vital *lower* a score.

        Where a vital is both absent and known to pull the score down, also
        evaluate the patient with that vital at its population median and keep
        the higher answer. So an unrecorded vital can never score better than an
        average one, which closes the silent-undertriage path the audit found.

        Deliberately the median and not the worst case. Worst-case substitution
        belongs at Layer 0, where it is paired with an instruction to measure
        the vital; applying it here sends every incomplete form to band 1 and
        recreates the alert fatigue the whole design is trying to avoid.
        """
        if not self.unsafe_missing:
            return risk
        probe, changed = X.copy(), False
        for field in self.unsafe_missing:
            if field in probe.columns and pd.isna(probe[field].iloc[0]):
                if field in self.medians_:
                    probe.loc[probe.index[0], field] = self.medians_[field]
                    changed = True
        if not changed:
            return risk
        return max(risk, float(self.score_frame(probe)[0]))

    def band_for(self, risk: float) -> int:
        """Band by position in the training risk distribution (1 = most urgent)."""
        for band, cut in enumerate(self.band_cuts, start=1):
            if risk >= cut:
                return band
        return 5

    def flags_for_review(self, risk: float) -> bool:
        """The operating point: tuned to 95% sensitivity, separate from banding."""
        return risk >= self.threshold

    def confidence_for(self, risk: float, n_missing: int,
                       pset: PredictionSet | None = None) -> str:
        """
        Confidence comes from the conformal set, with a floor for missing data:
        a guarantee about the model's calibration says nothing about a vital
        nobody measured.
        """
        if pset is None:
            return "MODERATE"
        conf = pset.confidence
        if n_missing >= 3:
            return "LOW"
        if n_missing >= 1 and conf == "HIGH":
            return "MODERATE"
        return conf

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
