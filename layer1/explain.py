"""
Why the model said what it said — feature attribution, not a rewritten rule.

The reasons Layer 1 already produced are honest but they are *descriptions*:
they name the pathway that engaged and the vitals that engaged it. They do not
tell you what the trained model actually weighed, and the two can disagree. A
patient can trip the respiratory pathway on a borderline respiratory rate while
the model's score is being driven mostly by age and a low blood pressure.

This closes that gap with TreeSHAP over the gradient-boosted trees. Every
contribution here is computed from the model, not asserted about it.

Two things it is deliberately not:

**It does not explain the whole system.** Layer 0 is a table of cited
thresholds; a fired rule explains itself and needs no attribution. Layer 2 is
arithmetic on deltas. This explains Layer 1 alone, which is the only part whose
reasoning is not already readable.

**It does not change any decision.** Nothing downstream reads these values. An
explanation that can alter what it explains is not an explanation.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

try:                                        # pragma: no cover - import guard
    import shap
    AVAILABLE = True
except Exception:                           # pragma: no cover
    shap = None
    AVAILABLE = False

#: Plain names. A nurse should not have to read `n_vitals_missing`.
LABEL = {
    "o2sat": "oxygen saturation", "sbp": "systolic blood pressure",
    "dbp": "diastolic blood pressure", "heartrate": "heart rate",
    "resprate": "breathing rate", "temperature": "temperature",
    "age": "age", "pain": "reported pain", "shock_index": "shock index",
    "pulse_pressure": "pulse pressure", "is_paediatric": "being a child",
    "is_geriatric": "being over 60", "arrived_by_ambulance": "arriving by ambulance",
    "n_vitals_missing": "how many vitals are unrecorded",
}
for _v in ("o2sat", "sbp", "dbp", "heartrate", "resprate", "temperature"):
    LABEL[f"{_v}_missing"] = f"{LABEL[_v]} not being recorded"


def label(column: str) -> str:
    return LABEL.get(column, column.replace("_", " "))


class Attributor:
    """
    TreeSHAP over the fitted model, built once and reused.

    Constructing the explainer walks the trees, so it is done at fit time rather
    than per patient. Explaining one row is then a few milliseconds, which is
    what makes it affordable on every score rather than a batch job nobody runs.
    """

    def __init__(self, model, columns: list[str]):
        self.columns = list(columns)
        self._explainer = None
        if AVAILABLE:
            try:
                self._explainer = shap.TreeExplainer(model)
            except Exception:
                # An explainer that cannot be built must not stop patients being
                # scored. The board falls back to the descriptive reasons.
                self._explainer = None

    @property
    def ready(self) -> bool:
        return self._explainer is not None

    def explain(self, X: pd.DataFrame, top: int = 4) -> list[dict[str, Any]]:
        """
        The features that moved this one prediction, largest effect first.

        `effect` is the SHAP value in log-odds. It is reported as a direction and
        a share of the total movement rather than as a raw number, because a
        log-odds contribution is not a quantity anyone can act on and presenting
        one as though it were is how an explanation becomes decoration.
        """
        if not self.ready or X.empty:
            return []
        try:
            values = self._explainer.shap_values(X.iloc[[0]][self.columns])
        except Exception:
            return []

        v = np.asarray(values)
        if v.ndim == 3:              # (rows, features, classes)
            v = v[0, :, -1]
        elif v.ndim == 2:
            v = v[0]

        total = float(np.abs(v).sum()) or 1.0
        order = np.argsort(-np.abs(v))[:top]

        out = []
        for i in order:
            column = self.columns[i]
            effect = float(v[i])
            if abs(effect) < 1e-9:
                continue
            raw = X.iloc[0].get(column)
            out.append({
                "feature": column,
                "label": label(column),
                "value": None if raw is None or pd.isna(raw) else round(float(raw), 2),
                "direction": "raised" if effect > 0 else "lowered",
                "effect": round(effect, 4),
                "share": round(abs(effect) / total, 3),
            })
        return out


def as_sentences(attributions: list[dict[str, Any]]) -> tuple[str, ...]:
    """The same attributions, in words, for a board that has no room for a chart."""
    out = []
    for a in attributions:
        value = "" if a["value"] is None else f" of {a['value']:g}"
        out.append(f"{a['label']}{value} {a['direction']} the score "
                   f"({a['share']:.0%} of the weight)")
    return tuple(out)
