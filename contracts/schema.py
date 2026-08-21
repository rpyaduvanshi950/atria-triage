"""
The schema contract — the single shared truth for ATRIA.

Every data source is mapped into MIMIC-IV-ED's column names by its loader, and
nothing above the loader layer ever sees a source-specific field name. Changing
anything in this file is a three-person decision: every integration failure this
week will otherwise trace back to a quiet rename.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

# --- column contracts, MIMIC-IV-ED v2.2 names exactly -----------------------

# One deliberate extension to the MIMIC names: `age`. ATRIA's vulnerability
# weights (<15 and >60) and paediatric thresholds need it, and MIMIC-IV-ED keeps
# age in the hosp module rather than the ED one. NA where a source cannot supply it.
EDSTAYS_COLS = [
    "subject_id", "stay_id", "intime", "outtime",
    "gender", "age", "race", "arrival_transport", "disposition",
]

TRIAGE_COLS = [
    "subject_id", "stay_id",
    "temperature", "heartrate", "resprate", "o2sat", "sbp", "dbp",
    "pain", "acuity", "chiefcomplaint",
]

VITALSIGN_COLS = [
    "subject_id", "stay_id", "charttime",
    "temperature", "heartrate", "resprate", "o2sat", "sbp", "dbp",
    "rhythm", "pain",
]

# The six vitals Layer 0 and Layer 1 reason over.
VITAL_FIELDS = ["temperature", "heartrate", "resprate", "o2sat", "sbp", "dbp"]

ACUITY_MIN, ACUITY_MOST_URGENT = 1, 1
ACUITY_MAX, ACUITY_LEAST_URGENT = 5, 5


@dataclass(frozen=True)
class Dataset:
    """One data source, mapped into the contract."""

    source: str
    edstays: pd.DataFrame
    triage: pd.DataFrame
    vitalsign: Optional[pd.DataFrame] = None
    extensions: dict = field(default_factory=dict)

    #: False when the source must not be used to fit a model. See Isfahan.
    trainable: bool = True
    #: Why not, if trainable is False. Surfaced on every misuse.
    not_trainable_reason: str = ""

    @property
    def has_trajectories(self) -> bool:
        """True when the source carries repeated vitals — i.e. Layer 2 can use it."""
        if self.vitalsign is None or self.vitalsign.empty:
            return False
        return int(self.vitalsign.groupby("stay_id").size().max() or 0) > 1

    def require_trainable(self) -> None:
        """Call before fitting anything. Refuses sources with known leakage."""
        if not self.trainable:
            raise LeakageError(
                f"{self.source} must not be used for training.\n"
                f"{self.not_trainable_reason}"
            )

    def summary(self) -> str:
        traj = self.vitalsign.groupby("stay_id").size() if self.vitalsign is not None else None
        parts = [
            f"{self.source}: {len(self.edstays):,} stays, {len(self.triage):,} triage rows",
        ]
        if traj is not None:
            parts.append(
                f"{len(self.vitalsign):,} vitalsign rows, "
                f"{int((traj >= 3).sum()):,} stays with >=3 readings"
            )
        parts.append("trainable" if self.trainable else "NOT TRAINABLE")
        return " | ".join(parts)


class LeakageError(RuntimeError):
    """Raised when a source with known target leakage is used for training."""


def conform(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Return df with exactly `cols`, adding missing ones as NA, in contract order."""
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = pd.NA
    return out[cols]


def validate(ds: Dataset) -> None:
    """Fail loudly if a loader has drifted from the contract."""
    assert list(ds.edstays.columns) == EDSTAYS_COLS, f"{ds.source}: edstays columns off contract"
    assert list(ds.triage.columns) == TRIAGE_COLS, f"{ds.source}: triage columns off contract"
    if ds.vitalsign is not None:
        assert list(ds.vitalsign.columns) == VITALSIGN_COLS, f"{ds.source}: vitalsign off contract"
    acuity = pd.to_numeric(ds.triage["acuity"], errors="coerce").dropna()
    if len(acuity):
        assert acuity.between(ACUITY_MIN, ACUITY_MAX).all(), (
            f"{ds.source}: acuity outside {ACUITY_MIN}-{ACUITY_MAX}"
        )
