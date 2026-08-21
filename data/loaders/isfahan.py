"""
Isfahan ED loader — 143,582 stays, CC BY 4.0.

NOT TRAINABLE. Missingness in this dataset encodes the triage decision itself
rather than clinical state: 100% of TriageGrade 1 patients have zero recorded
vitals, against 0% of TriageGrade 3. The sickest patients bypass the triage form
and go straight to resuscitation, so a model given missing-indicators would score
near-perfectly by learning hospital workflow instead of physiology. The leak
reaches the label too.

Use it for generator priors (age, complaint mix, grade distribution) and as the
data-quality case study. `Dataset.require_trainable()` refuses it for fitting.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from contracts.schema import (
    Dataset, EDSTAYS_COLS, TRIAGE_COLS, conform,
)

ROOT = Path("data/isfahan")

# from the bundled Tables_Descriptions.docx
KINDREF = {
    0: "self", 1: "referral_other_centre", 2: "referral_other_city",
    3: "ambulance", 4: "unknown", 5: "other", 6: "accompanied",
}

FIELD_MAP = {
    "BlooddpressurSystol": "sbp",
    "BlooddpressurDiastol": "dbp",
    "PulseRate": "heartrate",
    "RespiratoryRate": "resprate",
    "Temperature": "temperature",
    "O2Saturation": "o2sat",
    "PainGrade": "pain",
    "ChiefComplaint": "chiefcomplaint",
    "TriageGrade": "acuity",
}

LEAKAGE = (
    "Missingness encodes the triage grade: grade 1 has 100% zero-vitals, grade 3 "
    "has 0%. Patients with zero recorded vitals show a 9.2% outcome rate against "
    "0.4-2.8% for the rest. Training on this learns the hospital's workflow, not "
    "the patient. See data/README.md and the plan, section 03."
)


def load(root: Path | str = ROOT) -> Dataset:
    root = Path(root)
    if not (root / "ED_triage.csv").exists():
        raise FileNotFoundError(f"Isfahan not found at {root} — see data/README.md")

    tri = pd.read_csv(root / "ED_triage.csv", low_memory=False)
    adm = pd.read_csv(root / "ED_admission.csv", low_memory=False)

    # triage_code is documented as the join key but is NOT unique: 236 collisions
    # in triage and 56 in admission, where the same code maps to different
    # PatientCodes. Those rows are genuinely ambiguous, so drop rather than guess.
    dropped = {
        "triage": int(tri["triage_code"].duplicated(keep=False).sum()),
        "admission": int(adm["triage_code"].duplicated(keep=False).sum()),
    }
    tri = tri[~tri["triage_code"].duplicated(keep=False)]
    adm = adm[~adm["triage_code"].duplicated(keep=False)]

    tri = tri.rename(columns=FIELD_MAP)
    tri["stay_id"] = tri["triage_code"]

    adm_idx = adm.set_index("triage_code")
    tri["subject_id"] = tri["triage_code"].map(adm_idx["PatientCode"])

    intime = pd.to_datetime(dict(
        year=tri["admission_year"], month=tri["admission_month"],
        day=tri["admission_day"], hour=tri["admission_hour"],
    ), errors="coerce")

    edstays = pd.DataFrame({
        "subject_id": tri["subject_id"],
        "stay_id": tri["stay_id"],
        "intime": intime,
        "outtime": pd.NaT,
        "gender": tri["gender"],
        "age": tri["age"],
        "race": pd.NA,                      # not collected — fairness audit is sex/age only
        "arrival_transport": tri["kindref"].map(KINDREF),
        # StatusOnDischarge codes are NOT decoded by the bundled docx. Kept raw.
        "disposition": tri["stay_id"].map(adm_idx["StatusOnDischarge"]),
    })

    return Dataset(
        source="isfahan",
        edstays=conform(edstays, EDSTAYS_COLS),
        triage=conform(tri, TRIAGE_COLS),
        vitalsign=None,                     # one row per stay; no trajectories
        extensions={
            "avpu": tri[["stay_id", "AVPU"]],
            "critical_status": tri[["stay_id", "CriticalStatus"]],
            "ambiguous_keys_dropped": dropped,
        },
        trainable=False,
        not_trainable_reason=LEAKAGE,
    )


def missingness_report(ds: Dataset) -> pd.DataFrame:
    """Reproduces the section 03 table. Figures go straight on a slide."""
    from contracts.schema import VITAL_FIELDS
    tri = ds.triage
    grade = pd.to_numeric(tri["acuity"], errors="coerce")
    recorded = tri[VITAL_FIELDS].notna().sum(axis=1)
    out = pd.DataFrame({"grade": grade, "recorded": recorded}).dropna(subset=["grade"])
    return out.groupby("grade").agg(
        patients=("recorded", "size"),
        mean_recorded=("recorded", "mean"),
        pct_zero_vitals=("recorded", lambda s: 100 * (s == 0).mean()),
    ).round(2)
