"""
Auditing what the model learned about missingness.

The deck claims "unknown is not normal". Layer 0 enforces that by construction.
Layer 1 cannot: gradient-boosted trees learn their own NaN split direction from
data, and nothing guarantees that direction points toward risk.

So verify it rather than asserting it. For each vital, blank the field across a
sample and measure how the predicted risk moves. A field whose absence *lowers*
risk is a silent undertriage path, and gets clamped.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from contracts.schema import VITAL_FIELDS


def missingness_directions(scorer, X: pd.DataFrame, sample: int = 2000) -> pd.DataFrame:
    """Change in mean predicted risk when each vital is blanked."""
    Xs = X.sample(min(sample, len(X)), random_state=0) if len(X) > sample else X
    base = scorer.score_frame(Xs).mean()

    rows = []
    for field in VITAL_FIELDS:
        if field not in Xs.columns:
            continue
        probe = Xs.copy()
        probe[field] = np.nan
        if f"{field}_missing" in probe.columns:
            probe[f"{field}_missing"] = 1
            miss_cols = [c for c in probe.columns if c.endswith("_missing")]
            probe["n_vitals_missing"] = probe[miss_cols].sum(axis=1)
        delta = float(scorer.score_frame(probe).mean() - base)
        rows.append({
            "field": field,
            "baseline_risk": round(float(base), 4),
            "risk_when_missing": round(float(base + delta), 4),
            "delta": round(delta, 4),
            "direction": "raises risk" if delta > 0 else "LOWERS RISK",
            "safe": delta >= 0,
        })
    return pd.DataFrame(rows)


def unsafe_fields(scorer, X: pd.DataFrame, **kw) -> list[str]:
    """Vitals whose absence makes the model *less* worried. These need clamping."""
    report = missingness_directions(scorer, X, **kw)
    return report.loc[~report["safe"], "field"].tolist()
