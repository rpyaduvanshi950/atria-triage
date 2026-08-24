"""
The three atria mortis — the gates through which a patient dies.

Bichat's classical triad: the brain, the heart, the lungs. Every acute
presentation kills through one or more of them, and the point of naming them is
that it makes feature selection *follow from a clinical model* instead of being
a bag of vitals someone happened to have.

For each pathway we monitor four to five parameters, and we ask one question of
each: how far along this pathway is this patient? A trauma patient can be
travelling down all three at once, which is exactly the overlapping-pathology
case that a single acuity score cannot express.

ASSUMPTION TO CONFIRM against the Round 1 deck: the Round 1 material names
"Cerebral Hypoxia" as one pathway but does not enumerate the other two in the
files in this repo. The triad below is the classical one. If Round 1 defined
them differently, change PATHWAYS and nothing else needs to move.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import log

# Each pathway: the parameters we monitor, how each maps to involvement, and how
# *specific* it is to this gate. A "stop" is where that parameter alone means the
# pathway is fully engaged.
#
# Specificity matters more than it looks. SpO2, GCS and respiratory rate appear
# in more than one pathway, and weighting them equally everywhere makes all three
# gates light up together on any sick patient — which destroys the one thing this
# decomposition exists to give us, namely knowing *which* gate is closing.
#   weight 1.0  primary   this parameter defines the pathway
#   weight <1   supporting it is consistent with the pathway but not specific to it
PATHWAYS: dict[str, dict] = {
    "respiratory": {
        "label": "Respiratory failure",
        "gate": "the lungs",
        "params": {
            "o2sat":     {"direction": "low",  "normal": 96, "stop": 88, "w": 1.0},
            "resprate":  {"direction": "both", "normal": 16, "stop": 34, "low_stop": 8, "w": 1.0},
            "heartrate": {"direction": "high", "normal": 80, "stop": 140, "w": 0.25},
            "gcs":       {"direction": "low",  "normal": 15, "stop": 8, "w": 0.35},
        },
    },
    "circulatory": {
        "label": "Circulatory failure",
        "gate": "the heart",
        "params": {
            "sbp":          {"direction": "low",  "normal": 120, "stop": 80, "w": 1.0},
            "shock_index":  {"direction": "high", "normal": 0.6, "stop": 1.3, "w": 1.0},
            "pulse_pressure": {"direction": "low", "normal": 45, "stop": 20, "w": 0.6},
            "heartrate":    {"direction": "high", "normal": 80,  "stop": 140, "w": 0.4},
            "temperature":  {"direction": "low",  "normal": 98.6, "stop": 93.0, "w": 0.4},
        },
    },
    "neurological": {
        "label": "Cerebral hypoxia",
        "gate": "the brain",
        "params": {
            "gcs":      {"direction": "low",  "normal": 15, "stop": 8, "w": 1.0},
            "o2sat":    {"direction": "low",  "normal": 96, "stop": 88, "w": 0.45},
            "sbp":      {"direction": "low",  "normal": 120, "stop": 80, "w": 0.35},
            "resprate": {"direction": "both", "normal": 16, "stop": 34, "low_stop": 8, "w": 0.25},
        },
    },
}


def _involvement(value: float | None, spec: dict) -> float | None:
    """0 = this parameter looks normal, 1 = it alone closes the gate."""
    if value is None:
        return None
    normal, stop = spec["normal"], spec["stop"]
    direction = spec["direction"]

    if direction == "both":
        low_stop = spec.get("low_stop")
        if low_stop is not None and value < normal:
            return max(0.0, min(1.0, (normal - value) / (normal - low_stop)))
        direction = "high"

    if direction == "low":
        if value >= normal:
            return 0.0
        return max(0.0, min(1.0, (normal - value) / (normal - stop)))

    if value <= normal:
        return 0.0
    return max(0.0, min(1.0, (value - normal) / (stop - normal)))


@dataclass(frozen=True)
class PathwayProfile:
    """How far this patient is down each of the three gates."""

    scores: dict[str, float]
    observed: dict[str, int]          # how many parameters we could actually see
    drivers: dict[str, tuple[str, ...]]

    @property
    def dominant(self) -> str | None:
        if not self.scores or max(self.scores.values()) < 0.15:
            return None
        return max(self.scores, key=self.scores.get)

    @property
    def engaged(self) -> tuple[str, ...]:
        """Pathways meaningfully in play. More than one is the hard case."""
        return tuple(k for k, v in sorted(self.scores.items(), key=lambda kv: -kv[1])
                     if v >= 0.30)

    @property
    def severity(self) -> float:
        """Worst single pathway — a patient dies through one gate, not an average."""
        return max(self.scores.values()) if self.scores else 0.0

    @property
    def spread(self) -> float:
        """
        How close the runner-up gate is to the leading one.

        0 = one gate is clearly closing and the others are not
        1 = the picture is equally consistent with more than one

        This is *diagnostic* uncertainty — not knowing what is killing them. It
        is a different failure from *triage* uncertainty, which is not knowing
        how urgent they are, and the system reports the two separately. A patient
        can be unambiguously critical (low triage uncertainty) while nobody can
        say whether it is the heart, the lungs or the brain (high diagnostic
        uncertainty). That patient needs a doctor now, not a better score.
        """
        vals = sorted((v for v in self.scores.values()), reverse=True)
        if len(vals) < 2 or vals[0] <= 0.05:
            return 0.0
        return round(max(0.0, min(1.0, vals[1] / vals[0])), 4)

    def as_dict(self) -> dict:
        return dict(
            scores={k: round(v, 3) for k, v in self.scores.items()},
            dominant=self.dominant, engaged=list(self.engaged),
            severity=round(self.severity, 3), spread=round(self.spread, 3),
            drivers={k: list(v) for k, v in self.drivers.items() if v},
        )

    def explain(self) -> str:
        if not self.dominant:
            return "no pathway clearly engaged"
        parts = []
        for name in self.engaged:
            label = PATHWAYS[name]["label"]
            why = ", ".join(self.drivers.get(name, ())[:2])
            parts.append(f"{label} {self.scores[name]:.0%}" + (f" ({why})" if why else ""))
        return " · ".join(parts) or f"{PATHWAYS[self.dominant]['label']} emerging"


def assess(patient: dict) -> PathwayProfile:
    """Score every pathway from whatever parameters are actually present."""
    scores, observed, drivers = {}, {}, {}

    for name, spec in PATHWAYS.items():
        contributions: list[tuple[float, str]] = []
        seen = 0
        for param, pspec in spec["params"].items():
            value = patient.get(param)
            inv = _involvement(value, pspec)
            if inv is None:
                continue
            seen += 1
            weighted = inv * pspec.get("w", 1.0)
            if weighted > 0.05:
                contributions.append((weighted, f"{param} {value:g}"))

        observed[name] = seen
        if not contributions:
            scores[name] = 0.0
            drivers[name] = ()
            continue

        contributions.sort(reverse=True)
        # noisy-OR over weighted parameters: any one primary parameter can close
        # the gate on its own, and supporting parameters accumulate without a
        # pile of mildly abnormal readings ever reaching certainty by themselves
        product = 1.0
        for weighted, _ in contributions:
            product *= (1.0 - weighted)
        scores[name] = round(1.0 - product, 4)
        drivers[name] = tuple(label for _, label in contributions[:3])

    return PathwayProfile(scores, observed, drivers)
