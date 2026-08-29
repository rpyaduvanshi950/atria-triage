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
from eval.uncertainty import (bootstrap, conformal_quantile_index, gap_with_ci,
                              rate_with_ci)

EO_TOLERANCE = 0.05          # the "< 5 points" target on the results slide

#: A group whose own confidence interval is wider than the tolerance cannot
#: settle whether the tolerance is met — with 2 test positives the sensitivity
#: is somewhere between 16% and 100%, and whichever end you quote is a choice
#: rather than a measurement. Those groups are excluded from the gap and
#: reported separately, never dropped silently. The rule is stated in terms of
#: the tolerance rather than a patient count so it cannot be tuned after seeing
#: which groups it excludes.
GAP_NEEDS_CI_NARROWER_THAN = EO_TOLERANCE

#: Groups smaller than this get a threshold fitted to a handful of patients,
#: which is worse than no adjustment at all — it overfits the calibration split
#: and then fails on anyone new. They keep the global threshold and are reported
#: with their interval, so the audit shows them rather than hiding them.
MIN_POSITIVES_TO_FIT = 40


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
            # The interval, not just the point estimate: a subgroup audit exists
            # to protect small groups, and small groups are exactly where a bare
            # percentage misleads.
            sens = rate_with_ci(flagged[mask & (y == 1)])
            rows.append({
                "attribute": attribute, "group": value, "n": int(mask.sum()),
                "prevalence": round(float(y[mask].mean()), 4),
                "sensitivity": round(tpr, 4),
                "sens_ci_low": sens["ci_low"], "sens_ci_high": sens["ci_high"],
                "false_alarm_rate": round(fpr, 4),
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


def mitigate(scorer: AcuityScorer, ds: Dataset, attribute: str = "age_band",
             *, seed: int = 3, resolve_tolerance: float | None = None) -> dict:
    """
    Subgroup-conditional conformal, fitted on one split and measured on another.

    Three things changed here after the numbers stopped being believable:

    **The thresholds are fitted out of sample.** The previous version chose each
    group's threshold on the same patients it then scored, so every reported
    sensitivity was the quantile it had just been fitted to. That is not a
    result, it is a restatement of the fit, and it flattered the small groups
    most because they overfit hardest.

    **Small groups keep the global threshold.** A threshold fitted to twenty
    positives is noise dressed as personalisation.

    **Every rate carries an interval.** A gap of five points across groups of
    300,000 and 375 is mostly a statement about the 375.
    """
    X = features.build(ds)
    y = features.critical_outcome(ds).reindex(X.index).fillna(0).astype(int).to_numpy()
    p = scorer.score_frame(X)
    groups = subgroups(ds, X)[attribute].to_numpy()

    rng = np.random.default_rng(seed)
    calibrate = rng.random(len(y)) < 0.5
    test = ~calibrate

    alpha = 1 - scorer.sensitivity_target
    mc = MondrianConformal(alpha=alpha).fit(p[calibrate], y[calibrate],
                                            groups[calibrate])

    per_group: dict[str, float] = {}
    fitted: dict[str, bool] = {}
    for g in np.unique(groups):
        pos = np.sort(p[(groups == g) & (y == 1) & calibrate])
        if len(pos) < MIN_POSITIVES_TO_FIT:
            per_group[str(g)] = scorer.threshold
            fitted[str(g)] = False
            continue
        per_group[str(g)] = float(pos[conformal_quantile_index(len(pos), alpha)])
        fitted[str(g)] = True

    rows = []
    for g, thr in per_group.items():
        mask = (groups == g) & test & (y == 1)      # sensitivity is about the sick
        if mask.sum() == 0:
            continue
        after = rate_with_ci(p[mask] >= thr)
        before = rate_with_ci(p[mask] >= scorer.threshold)
        neg = (groups == g) & test & (y == 0)
        rows.append({
            "group": g, "n_test_positive": int(mask.sum()),
            "threshold_fitted": fitted[g],
            "sensitivity_before": before["rate"],
            "sensitivity_after": after["rate"],
            "ci_low": after["ci_low"], "ci_high": after["ci_high"],
            "ci_width": after["ci_width"],
            "false_alarm_before": rate_with_ci(p[neg] >= scorer.threshold)["rate"],
            "false_alarm_after": rate_with_ci(p[neg] >= thr)["rate"],
            "threshold": round(thr, 5),
        })
    after = pd.DataFrame(rows).sort_values("sensitivity_after")

    # The gap between the best- and worst-served group, with an interval. If it
    # contains zero, the gap is not resolvable at this sample size — which is a
    # different claim from "the model is fair", and the honest one to make.
    # Defaults to the reporting tolerance. Exposed as a parameter only so a test
    # on a few thousand synthetic patients can still exercise the logic — real
    # subgroups need several hundred positives before a rate can be pinned to
    # five points, and the published figures always use the default.
    tol = GAP_NEEDS_CI_NARROWER_THAN if resolve_tolerance is None else resolve_tolerance
    resolvable = after[after["ci_width"] <= tol]
    unresolvable = after[after["ci_width"] > tol]
    if len(resolvable) >= 2:
        worst = resolvable.iloc[0]["group"]
        best = resolvable.iloc[-1]["group"]
        flags = {g: (p[(groups == g) & test & (y == 1)] >= per_group[g])
                 for g in (worst, best)}
        gap = gap_with_ci(flags[best], flags[worst])
    else:
        worst = best = None
        gap = {"gap": None, "ci_low": None, "ci_high": None,
               "distinguishable": None}

    return {
        "attribute": attribute,
        "thresholds": per_group,
        "conformal_coverage": mc.coverage,
        "n_calibrate": int(calibrate.sum()), "n_test": int(test.sum()),
        "tpr_gap_before": round(float(resolvable["sensitivity_before"].max()
                                      - resolvable["sensitivity_before"].min()), 4)
        if len(resolvable) >= 2 else None,
        "tpr_gap_after": round(float(resolvable["sensitivity_after"].max()
                                     - resolvable["sensitivity_after"].min()), 4)
        if len(resolvable) >= 2 else None,
        "groups_too_small_to_resolve": list(unresolvable["group"]),
        "resolve_tolerance": tol,
        "gap_ci": gap,
        "worst_served": worst, "best_served": best,
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
    attr = "race" if "race" in set(report["attribute"]) else "age_band"
    m = mitigate(scorer, ds, attr)
    print(m["detail"].to_string(index=False))
    print(f"\nTPR gap  before {m['tpr_gap_before']:.1%}  ->  after {m['tpr_gap_after']:.1%}")
    g = m["gap_ci"]
    print(f"residual gap {g['gap']:.1%}  95% CI [{g['ci_low']:.1%}, {g['ci_high']:.1%}]"
          f"  ({m['best_served']} vs {m['worst_served']})")
    print("distinguishable from zero:", g["distinguishable"],
          f"| within the {EO_TOLERANCE:.0%} tolerance:",
          abs(g["gap"]) <= EO_TOLERANCE)
    if m["groups_too_small_to_resolve"]:
        print("too small to resolve at this tolerance, excluded from the gap and "
              "reported anyway: " + ", ".join(m["groups_too_small_to_resolve"]))
    print(f"fitted out of sample: {m['n_calibrate']:,} calibrate / {m['n_test']:,} test")
    print(f"per-group conformal coverage: {m['conformal_coverage']}")


if __name__ == "__main__":
    main()
