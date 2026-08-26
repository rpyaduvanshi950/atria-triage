"""
Does the model survive leaving the hospital it was trained on?

Yale ships three hospitals in `dep_name`, which gives a genuine cross-site test
for free: train on two, evaluate on the third. Until the Yale extraction is done
this falls back to a cross-*source* check — train on the calibrated generator,
evaluate on the MIMIC demo — which is weaker but tests the same failure mode.

Report the drop honestly. A model that holds up is evidence; one that does not
is the calibration-drift argument for per-site recalibration, which belongs in
the roadmap either way.
"""
from __future__ import annotations

import pandas as pd
from sklearn.metrics import roc_auc_score

import data.loaders as loaders
from layer1 import features
from layer1.model import AcuityScorer


def yale_cross_site(holdout: str | None = None) -> dict:
    ds = loaders.load("yale")
    ext = ds.extensions.get("fairness_and_history")
    if ext is None or "dep_name" not in ext.columns:
        raise RuntimeError("Yale slim CSV has no dep_name column")

    site = ext.set_index("stay_id")["dep_name"]
    X, y = features.build(ds), features.critical_outcome(ds)
    sites = sorted(site.dropna().unique())
    holdout = holdout or sites[-1]

    train_mask = site.reindex(X.index) != holdout
    tr = _fit_on(ds, X[train_mask], y[train_mask])
    out = {"holdout_site": holdout, "sites": sites}
    for s in sites:
        m = site.reindex(X.index) == s
        if m.sum() < 50 or y[m].nunique() < 2:
            continue
        out[f"auc_{s}"] = round(float(roc_auc_score(y[m], tr.score_frame(X[m]))), 4)
        out[f"n_{s}"] = int(m.sum())
    return out


def _fit_on(ds, X: pd.DataFrame, y: pd.Series) -> AcuityScorer:
    # Holding out a hospital makes dep_name constant in the training split, and a
    # constant column crashes the histogram binner. Drop whatever this split
    # cannot support, exactly as AcuityScorer.fit does.
    usable = [c for c in X.columns if X[c].nunique(dropna=True) >= 2]
    m = AcuityScorer()
    m.columns = list(usable)
    from sklearn.ensemble import HistGradientBoostingClassifier
    m.model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08,
                                             max_depth=6, early_stopping=False,
                                             random_state=0).fit(X[usable], y)
    return m


def cross_source() -> dict:
    """Fallback: train on synthetic, evaluate on real MIMIC demo stays."""
    train = loaders.load("synthetic", n=3000, seed=3)
    scorer = AcuityScorer().fit(train)

    test = loaders.load("mimic_demo")
    X, y = features.build(test), features.critical_outcome(test)
    keep = y.notna()
    if y[keep].nunique() < 2:
        return {"error": "single-class outcome on the demo set"}
    auc = roc_auc_score(y[keep], scorer.score_frame(X[keep]))
    return {
        "trained_on": "synthetic (n=3000, priors from Isfahan)",
        "evaluated_on": f"mimic_demo (n={int(keep.sum())} stays)",
        "auc_in_domain": scorer.metrics.get("auc"),
        "auc_out_of_domain": round(float(auc), 4),
        "drop": round(float(scorer.metrics.get("auc", 0) - auc), 4),
        "caveat": ("the label also changes: synthetic scores physiological "
                   "deterioration, MIMIC scores admission. This drop mixes "
                   "domain shift with label shift and is an upper bound on "
                   "the former. Yale's dep_name split is the clean test."),
    }


def main() -> None:
    try:
        r = yale_cross_site()
        print("Yale cross-site (train on two hospitals, evaluate on each):")
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"Yale unavailable ({str(exc).splitlines()[0]})")
        print("falling back to cross-source generalisation\n")
        r = cross_source()
    for k, v in r.items():
        print(f"  {k:<22} {v}")


if __name__ == "__main__":
    main()
