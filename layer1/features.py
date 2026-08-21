"""
Layer 1 feature construction — the ~12 fields available within five minutes.

Missingness is passed through natively rather than imputed: HistGradientBoosting
learns its own split direction for NaN, and an explicit `_missing` indicator per
vital is added alongside, because *which* vitals went unrecorded is itself signal
about how a triage encounter went.

That technique is right for Yale, where missingness is clinical. It is exactly
wrong for Isfahan, where missingness encodes the triage decision — which is why
Isfahan is marked not trainable. See data/README.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from contracts.schema import Dataset, VITAL_FIELDS

NUMERIC = [*VITAL_FIELDS, "pain", "age"]
DERIVED = ["shock_index", "pulse_pressure", "is_paediatric", "is_geriatric"]


def build(ds: Dataset) -> pd.DataFrame:
    """One row per stay, indexed by stay_id."""
    tri = ds.triage.set_index("stay_id")
    stays = ds.edstays.set_index("stay_id")

    X = pd.DataFrame(index=tri.index)
    for c in VITAL_FIELDS + ["pain"]:
        X[c] = pd.to_numeric(tri[c], errors="coerce")
    X["age"] = pd.to_numeric(stays["age"].reindex(tri.index), errors="coerce")

    # missingness as explicit signal
    for c in VITAL_FIELDS:
        X[f"{c}_missing"] = X[c].isna().astype(int)
    X["n_vitals_missing"] = X[[f"{c}_missing" for c in VITAL_FIELDS]].sum(axis=1)

    # derived physiology
    X["shock_index"] = X["heartrate"] / X["sbp"].replace(0, np.nan)
    X["pulse_pressure"] = X["sbp"] - X["dbp"]

    # ATRIA's stated vulnerability weights
    X["is_paediatric"] = (X["age"] < 15).astype(float).where(X["age"].notna())
    X["is_geriatric"] = (X["age"] > 60).astype(float).where(X["age"].notna())

    transport = stays["arrival_transport"].reindex(tri.index).astype(str).str.lower()
    X["arrived_by_ambulance"] = transport.str.contains("ambul").astype(int)

    return X


def critical_outcome(ds: Dataset) -> pd.Series:
    """
    The label. Definition depends on what the source can actually support —
    state which one you used, on the slide.

      yale       hospital admission (a coarse acuity proxy, not ICU-or-death)
      synthetic  reached a physiologically critical state during the stay
      mimic_demo admitted or transferred
    """
    if ds.source == "synthetic":
        v = ds.vitalsign
        crit = (
            (pd.to_numeric(v["o2sat"], errors="coerce") < 90)
            | (pd.to_numeric(v["sbp"], errors="coerce") < 90)
            | (pd.to_numeric(v["heartrate"], errors="coerce") > 130)
        )
        hit = v.assign(_c=crit).groupby("stay_id")["_c"].max()
        return hit.reindex(ds.triage["stay_id"]).fillna(False).astype(int).set_axis(ds.triage["stay_id"])

    disp = ds.edstays.set_index("stay_id")["disposition"].reindex(ds.triage["stay_id"])
    if ds.source == "yale":
        y = pd.to_numeric(disp, errors="coerce").fillna(0)
    else:
        y = disp.astype(str).str.upper().isin(["ADMITTED", "TRANSFER"]).astype(int)
    return y.astype(int).set_axis(ds.triage["stay_id"])
