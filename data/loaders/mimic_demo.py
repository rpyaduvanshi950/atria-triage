"""
MIMIC-IV-ED Demo v2.2 loader.

222 stays, 1,038 vitalsign rows, 159 stays with >=3 repeated readings at roughly
15-minute intervals. This is the only real trajectory data in the project and the
only real data that may legally appear on screen, so it carries Layer 2.

Licence: ODbL v1.0 — attribution and share-alike. See data/README.md.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from contracts.schema import (
    Dataset, EDSTAYS_COLS, TRIAGE_COLS, VITALSIGN_COLS, conform,
)

ROOT = Path("data/mimic_ed_demo")


def load(root: Path | str = ROOT) -> Dataset:
    root = Path(root)
    if not (root / "edstays.csv").exists():
        raise FileNotFoundError(f"MIMIC demo not found at {root} — see data/README.md")

    # quoting matters: chiefcomplaint contains unescaped commas inside quotes
    edstays = pd.read_csv(root / "edstays.csv", quotechar='"')
    triage = pd.read_csv(root / "triage.csv", quotechar='"')
    vitals = pd.read_csv(root / "vitalsign.csv", quotechar='"')

    edstays["intime"] = pd.to_datetime(edstays["intime"], errors="coerce")
    edstays["outtime"] = pd.to_datetime(edstays["outtime"], errors="coerce")
    vitals["charttime"] = pd.to_datetime(vitals["charttime"], errors="coerce")

    # age lives in the hosp module, which the ED demo does not ship
    edstays["age"] = pd.NA

    vitals = vitals.sort_values(["stay_id", "charttime"])

    return Dataset(
        source="mimic_ed_demo",
        edstays=conform(edstays, EDSTAYS_COLS),
        triage=conform(triage, TRIAGE_COLS),
        vitalsign=conform(vitals, VITALSIGN_COLS),
        extensions={"diagnosis": root / "diagnosis.csv", "pyxis": root / "pyxis.csv"},
        trainable=True,
    )
