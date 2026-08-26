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


#: Triage-time context beyond the vitals. Everything here is known the moment
#: the patient is booked in — no history, no labs — so a model using it is still
#: comparable to a "triage variables only" benchmark.
CONTEXT_COLS = ("dep_name", "lang", "ethnicity", "insurance_status", "arrivalhour_bin")

#: Prior-use counts and last disposition. Known at triage for a returning
#: patient, but they are *history*, and the published benchmarks separate
#: triage-only (AUC 0.87) from triage-plus-history (0.92). Kept out by default so
#: the comparison stays honest; pass history=True to include them.
HISTORY_COLS = ("previousdispo", "n_edvisits", "n_admissions", "n_surgeries")


def _codes(series: pd.Series) -> pd.Series:
    """Stable integer codes for a categorical column; -1 for missing."""
    return series.astype("category").cat.codes.astype(float).replace(-1, np.nan)


def build(ds: Dataset, *, history: bool = False) -> pd.DataFrame:
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
    X["arrival_mode"] = _codes(transport)

    # The nurse's own triage level, as an *input*. This is not the same as
    # training on it: the label remains the clinical outcome, so the model can
    # and does disagree with the nurse. Excluding it would mean discarding the
    # single most informative thing available at triage, and the published
    # benchmark includes it.
    X["esi"] = pd.to_numeric(tri["acuity"], errors="coerce")

    for col in ("gender", "race"):
        if col in stays.columns and stays[col].notna().any():
            X[col] = _codes(stays[col].reindex(tri.index).astype(str))

    ext = ds.extensions.get("fairness_and_history")
    if ext is not None and not isinstance(ext, (str, bytes)):
        ext = ext.set_index("stay_id").reindex(tri.index)
        wanted = CONTEXT_COLS + (HISTORY_COLS if history else ())
        for col in wanted:
            if col not in ext.columns:
                continue
            values = ext[col]
            X[col] = (pd.to_numeric(values, errors="coerce")
                      if pd.api.types.is_numeric_dtype(values) else _codes(values.astype(str)))

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
        # Yale ships the outcome as the strings "Admit" / "Discharge", not 0/1.
        # Coercing to numeric silently yields an all-zero label and a model that
        # trains happily on nothing.
        y = disp.astype(str).str.strip().str.lower().eq("admit").astype(int)
    else:
        y = disp.astype(str).str.upper().isin(["ADMITTED", "TRANSFER"]).astype(int)
    return y.astype(int).set_axis(ds.triage["stay_id"])
