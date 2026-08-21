"""
Yale ED loader — 560,486 visits, 3 hospitals. The primary Layer 1 source.

Reads the slim CSV produced by data/yale/extract_yale.R. The raw .RData expands
to ~3.9 GB and cannot be loaded by pyreadr on a 16 GB machine, so extraction is a
one-off R step. See data/README.md.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from contracts.schema import (
    Dataset, EDSTAYS_COLS, TRIAGE_COLS, conform,
)

SLIM = Path("data/yale/yale_triage_slim.csv")

FIELD_MAP = {
    "triage_vital_hr": "heartrate",
    "triage_vital_sbp": "sbp",
    "triage_vital_dbp": "dbp",
    "triage_vital_rr": "resprate",
    "triage_vital_o2": "o2sat",
    "triage_vital_temp": "temperature",
    "esi": "acuity",
    "arrivalmode": "arrival_transport",
}

# Plausible ranges, used to catch the label rotation described below.
PLAUSIBLE = {
    "heartrate": (30, 200), "sbp": (60, 250), "dbp": (30, 150),
    "resprate": (5, 60), "o2sat": (50, 100), "temperature": (90, 110),
}

EXTRACT_HINT = (
    f"{SLIM} not found.\n"
    "Yale ships as R binary. Extract it once:\n"
    "    sudo apt install r-base\n"
    "    Rscript data/yale/extract_yale.R\n"
    "or run the same script in Google Colab and download the CSV.\n"
    "See data/README.md."
)


def load(path: Path | str = SLIM) -> Dataset:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(EXTRACT_HINT)

    df = pd.read_csv(path, low_memory=False)
    df = df.rename(columns=FIELD_MAP)
    df["stay_id"] = range(1, len(df) + 1)
    df["subject_id"] = pd.NA           # de-identified; no stable patient key shipped

    edstays = pd.DataFrame({
        "subject_id": df["subject_id"],
        "stay_id": df["stay_id"],
        "intime": pd.NaT,              # only month/day/hour-bin are released
        "outtime": pd.NaT,
        "gender": df.get("gender"),
        "age": df.get("age"),
        "race": df.get("race"),
        "arrival_transport": df.get("arrival_transport"),
        "disposition": df.get("disposition"),
    })

    ext_cols = [c for c in ("dep_name", "lang", "ethnicity", "insurance_status",
                            "previousdispo", "n_edvisits", "n_admissions",
                            "n_surgeries", "arrivalmonth", "arrivalday",
                            "arrivalhour_bin", "triage_vital_o2_device")
                if c in df.columns]

    return Dataset(
        source="yale",
        edstays=conform(edstays, EDSTAYS_COLS),
        triage=conform(df, TRIAGE_COLS),
        vitalsign=None,                # snapshot only; Layer 2 uses MIMIC + synthetic
        extensions={"fairness_and_history": df[["stay_id", *ext_cols]] if ext_cols else None},
        trainable=True,
    )


def check_vital_ranges(ds: Dataset) -> pd.DataFrame:
    """
    The paper's variable table has the hr/sbp/dbp descriptions rotated by one row
    (triage_vital_hr is described as "systolic blood pressure"). Run this before
    building any feature: if medians land outside the plausible band, the columns
    are mislabelled and every downstream number is poisoned.
    """
    rows = []
    for col, (lo, hi) in PLAUSIBLE.items():
        if col not in ds.triage.columns:
            continue
        x = pd.to_numeric(ds.triage[col], errors="coerce").dropna()
        if x.empty:
            continue
        med = float(x.median())
        rows.append({
            "field": col, "median": round(med, 1),
            "p01": round(float(x.quantile(0.01)), 1),
            "p99": round(float(x.quantile(0.99)), 1),
            "expected": f"{lo}-{hi}",
            "verdict": "ok" if lo <= med <= hi else "SUSPECT — check mapping",
        })
    return pd.DataFrame(rows)
