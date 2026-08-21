"""
Local explanations for a single score.

Occlusion attribution, not SHAP: each feature is replaced by its population
median and the change in predicted risk recorded. It is a coarser attribution
than Shapley values, but it is fast enough to run inside the live scoring path
and it is honest about what it measures. Named for what it is.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PRETTY = {
    "o2sat": "SpO2 {v:.0f}%", "sbp": "SBP {v:.0f}", "dbp": "DBP {v:.0f}",
    "heartrate": "HR {v:.0f}", "resprate": "RR {v:.0f}",
    "temperature": "temp {v:.1f}", "shock_index": "shock index {v:.2f}",
    "pulse_pressure": "pulse pressure {v:.0f}", "age": "age {v:.0f}",
    "pain": "pain {v:.0f}/10", "is_paediatric": "paediatric weighting",
    "is_geriatric": "geriatric weighting", "n_vitals_missing": "{v:.0f} vitals unrecorded",
    "arrived_by_ambulance": "arrived by ambulance",
}


class Explainer:
    def __init__(self, scorer, background: pd.DataFrame):
        self.scorer = scorer
        self.medians = background.median(numeric_only=True)

    def top_reasons(self, row: dict, k: int = 3) -> tuple[str, ...]:
        """The k features pushing this patient's risk up the most."""
        X = pd.DataFrame([row]).reindex(columns=self.scorer.columns)
        base = float(self.scorer.score_frame(X)[0])

        contributions = []
        for col in self.scorer.columns:
            if col.endswith("_missing") or col not in self.medians.index:
                continue
            probe = X.copy()
            probe[col] = self.medians[col]
            delta = base - float(self.scorer.score_frame(probe)[0])
            if delta > 0:                       # only what raised the risk
                contributions.append((delta, col, X[col].iloc[0]))

        contributions.sort(reverse=True, key=lambda t: t[0])
        out = []
        for _, col, value in contributions[:k]:
            tmpl = PRETTY.get(col)
            if tmpl is None:
                continue
            out.append(tmpl.format(v=value) if "{v" in tmpl else tmpl)
        return tuple(out) or (f"composite risk {base:.2f}",)
