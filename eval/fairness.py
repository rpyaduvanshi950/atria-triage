"""
Who does this model fail, and by how much?

Obermeyer et al. (Science, 2019) found a widely deployed US risk algorithm cut
the share of Black patients identified for extra care from 46.5% to 17.7% by
using cost as a proxy for need. The deck cites that as a warning. This turns the
warning into a measurement, and then into a mitigation.

Audited at the operating point, per subgroup:
  TPR gap   difference in sensitivity — who gets *missed*. The one that matters.
  FPR gap   difference in false alarms — who gets over-triaged.
  equalised-odds difference = max(TPR gap, FPR gap)

Mitigation is subgroup-conditional conformal: Mondrian takes an arbitrary
taxonomy, so calibrating on class x subgroup gives each subgroup its own
coverage guarantee rather than a shared average that hides the worst-served
group inside it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from contracts.schema import Dataset
from layer1 import features
from layer1.conformal import MondrianConformal
from layer1.model import AcuityScorer

EO_TOLERANCE = 0.05          # the "< 5 points" target on the results slide


def subgroups(ds: Dataset, X: pd.DataFrame) -> pd.DataFrame:
    """Whatever protected attributes the source actually carries. Name the gaps."""
    stays = ds.edstays.set_index("stay_id").reindex(X.index)
    age = pd.to_numeric(stays["age"], errors="coerce")
    out = pd.DataFrame(index=X.index)
    out["age_band"] = np.where(age < 15, "paediatric",
                               np.where(age > 60, "geriatric", "adult"))
    out["sex"] = stays["gender"].fillna("unknown").astype(str)
    for col in ("race", "ethnicity", "lang", "insurance_status"):
        if col in stays.columns and stays[col].notna().any():
            out[col] = stays[col].fillna("unknown").astype(str)
    return out


def _rates(y: np.ndarray, flagged: np.ndarray) -> tuple[float, float]:
    pos, neg = y == 1, y == 0
    tpr = float(flagged[pos].mean()) if pos.any() else np.nan
    fpr = float(flagged[neg].mean()) if neg.any() else np.nan
    return tpr, fpr


def audit(scorer: AcuityScorer, ds: Dataset, *, min_n: int = 30) -> pd.DataFrame:
    X = features.build(ds)
    y = features.critical_outcome(ds).reindex(X.index).fillna(0).astype(int).to_numpy()
    p = scorer.score_frame(X)
    flagged = p >= scorer.threshold
    groups = subgroups(ds, X)

    rows = []
    for attribute in groups.columns:
        for value, idx in groups.groupby(attribute).groups.items():
            mask = groups.index.isin(idx)
            if mask.sum() < min_n:
                continue
            tpr, fpr = _rates(y[mask], flagged[mask])
            rows.append({
                "attribute": attribute, "group": value, "n": int(mask.sum()),
                "prevalence": round(float(y[mask].mean()), 4),
                "sensitivity": round(tpr, 4), "false_alarm_rate": round(fpr, 4),
                "undertriage": round(1 - tpr, 4) if tpr == tpr else np.nan,
            })
    return pd.DataFrame(rows)


def equalised_odds(report: pd.DataFrame) -> pd.DataFrame:
    """Worst within-attribute gap. This is the number for the slide."""
    rows = []
    for attribute, g in report.groupby("attribute"):
        if len(g) < 2:
            continue
        tpr_gap = float(g["sensitivity"].max() - g["sensitivity"].min())
        fpr_gap = float(g["false_alarm_rate"].max() - g["false_alarm_rate"].min())
        worst = g.loc[g["sensitivity"].idxmin()]
        rows.append({
            "attribute": attribute,
            "tpr_gap": round(tpr_gap, 4),
            "fpr_gap": round(fpr_gap, 4),
            "equalised_odds_diff": round(max(tpr_gap, fpr_gap), 4),
            "worst_served": f"{worst['group']} ({worst['sensitivity']:.1%} sensitivity)",
            "within_tolerance": max(tpr_gap, fpr_gap) <= EO_TOLERANCE,
        })
    return pd.DataFrame(rows)


def mitigate(scorer: AcuityScorer, ds: Dataset, attribute: str = "age_band") -> dict:
    """
    Subgroup-conditional conformal, plus per-subgroup thresholds tuned to the
    same sensitivity target. Each group then gets the guarantee, rather than a
    shared average that buries the worst-served group inside it.
    """
    X = features.build(ds)
    y = features.critical_outcome(ds).reindex(X.index).fillna(0).astype(int).to_numpy()
    p = scorer.score_frame(X)
    groups = subgroups(ds, X)[attribute].to_numpy()

    mc = MondrianConformal(alpha=1 - scorer.sensitivity_target).fit(p, y, groups)

    per_group = {}
    for g in np.unique(groups):
        mask = (groups == g) & (y == 1)
        if mask.sum() < 5:
            continue
        pos = np.sort(p[mask])
        idx = int(np.floor((1 - scorer.sensitivity_target) * len(pos)))
        per_group[str(g)] = float(pos[min(idx, len(pos) - 1)])

    rows = []
    for g, thr in per_group.items():
        mask = groups == g
        tpr, fpr = _rates(y[mask], p[mask] >= thr)
        base_tpr, base_fpr = _rates(y[mask], p[mask] >= scorer.threshold)
        rows.append({"group": g, "n": int(mask.sum()),
                     "sensitivity_before": round(base_tpr, 4),
                     "sensitivity_after": round(tpr, 4),
                     "false_alarm_before": round(base_fpr, 4),
                     "false_alarm_after": round(fpr, 4),
                     "threshold": round(thr, 5)})
    after = pd.DataFrame(rows)
    return {
        "attribute": attribute,
        "thresholds": per_group,
        "conformal_coverage": mc.coverage,
        "tpr_gap_before": round(float(after["sensitivity_before"].max()
                                      - after["sensitivity_before"].min()), 4),
        "tpr_gap_after": round(float(after["sensitivity_after"].max()
                                     - after["sensitivity_after"].min()), 4),
        "detail": after,
    }


def main() -> None:
    from data.loaders.synthetic import generate
    import data.loaders as loaders

    try:
        ds = loaders.load("yale")
        source = "Yale (real race, ethnicity, language, insurance)"
    except FileNotFoundError:
        ds = generate(6000, seed=3)
        source = "synthetic (sex and age band only — Yale adds race/language/insurance)"

    scorer = AcuityScorer().fit(ds)
    report = audit(scorer, ds)

    print(f"source: {source}\n")
    print("=== per-subgroup performance at the operating point ===")
    print(report.to_string(index=False))

    eo = equalised_odds(report)
    print("\n=== equalised-odds gaps ===")
    print(eo.to_string(index=False))
    print(f"\ntolerance: {EO_TOLERANCE:.0%}")

    print("\n=== mitigation: subgroup-conditional conformal + thresholds ===")
    m = mitigate(scorer, ds)
    print(m["detail"].to_string(index=False))
    print(f"\nTPR gap  before {m['tpr_gap_before']:.1%}  ->  after {m['tpr_gap_after']:.1%}")
    print(f"per-group conformal coverage: {m['conformal_coverage']}")


if __name__ == "__main__":
    main()
