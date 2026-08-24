"""
Competing and compounding pathologies.

Two conditions are rarely additive. Sometimes they amplify each other, and
sometimes the treatment for one actively harms the other — which is the case
that matters, because it is where a confident single number is most dangerous.

The worked example from clinical review: hypothermia plus trauma. Give a
vasopressor for the shock and you constrict already-vasoconstricted peripheral
vessels, drive necrosis, and turn a limb-saving problem into an amputation. The
triage system does not and must not choose the drug — but it *can* say "these
two things are both true and they conflict", and route the patient to a human
who will make that call.

Nothing here changes clinical management. It changes who gets looked at first,
and it makes the reason legible.
"""
from __future__ import annotations

from dataclasses import dataclass

# Conditions detectable from the vitals we actually hold. Deliberately shallow —
# this is not a diagnostic engine, it is a conflict detector.
CONDITIONS = {
    "hypothermia":   lambda p: _lt(p.get("temperature"), 95.0),
    "hyperthermia":  lambda p: _gt(p.get("temperature"), 101.5),
    "shock":         lambda p: _gt(p.get("shock_index"), 1.0) or _lt(p.get("sbp"), 90),
    "hypoxia":       lambda p: _lt(p.get("o2sat"), 92),
    "bradycardia":   lambda p: _lt(p.get("heartrate"), 50),
    "tachypnoea":    lambda p: _gt(p.get("resprate"), 28),
    "depressed_consciousness": lambda p: _lt(p.get("gcs"), 13),
    "hypertension":  lambda p: _gt(p.get("sbp"), 180),
}


@dataclass(frozen=True)
class Interaction:
    a: str
    b: str
    kind: str            # "conflict" — treatments oppose | "synergy" — risk compounds
    note: str
    amplify: float       # multiplier applied to pathway severity
    citation: str

    def describe(self) -> str:
        return f"{self.a.replace('_', ' ')} + {self.b.replace('_', ' ')} — {self.note}"


INTERACTIONS: tuple[Interaction, ...] = (
    Interaction(
        "hypothermia", "shock", "conflict",
        "vasopressors risk peripheral necrosis in an already vasoconstricted patient; "
        "rewarming and pressor strategy conflict — clinician decision",
        1.35,
        "Trauma-induced coagulopathy / lethal triad: hypothermia, acidosis, coagulopathy. "
        "ATLS 10th ed.",
    ),
    Interaction(
        "hypoxia", "shock", "synergy",
        "oxygen delivery fails at both ends — content and flow — so tissue hypoxia "
        "compounds faster than either alone suggests",
        1.30,
        "Oxygen delivery DO2 = cardiac output x arterial oxygen content.",
    ),
    Interaction(
        "depressed_consciousness", "hypoxia", "synergy",
        "airway protection is failing while oxygenation is already inadequate",
        1.40,
        "ATLS 10th ed. — airway precedes breathing precedes circulation.",
    ),
    Interaction(
        "hyperthermia", "tachypnoea", "synergy",
        "consistent with sepsis; each hour of delayed antibiotics adds measurable mortality",
        1.25,
        "Liu et al., Am J Respir Crit Care Med 2017 — +1.8% absolute mortality per hour.",
    ),
    Interaction(
        "bradycardia", "hypertension", "conflict",
        "Cushing reflex — raised intracranial pressure. Lowering the blood pressure "
        "may reduce cerebral perfusion; this is the opposite of routine management",
        1.45,
        "Cushing's triad: hypertension, bradycardia, irregular respiration.",
    ),
    Interaction(
        "hypothermia", "bradycardia", "synergy",
        "cold myocardium is irritable and poorly responsive to drugs and pacing",
        1.20,
        "AHA 2020 — accidental hypothermia, limited drug efficacy below 30 C.",
    ),
)


def _lt(value, limit) -> bool:
    return value is not None and value == value and value < limit


def _gt(value, limit) -> bool:
    return value is not None and value == value and value > limit


def present(patient: dict) -> tuple[str, ...]:
    """Which shallow conditions are detectable right now."""
    return tuple(name for name, test in CONDITIONS.items() if test(patient))


def detect(patient: dict) -> tuple[Interaction, ...]:
    """Interactions where both sides are present."""
    active = set(present(patient))
    return tuple(i for i in INTERACTIONS if i.a in active and i.b in active)


def amplification(patient: dict) -> float:
    """
    Combined multiplier on pathway severity. Capped, because a patient with four
    interacting problems is not four times sicker than the worst of them — and an
    uncapped product would let this quietly dominate the whole score.
    """
    factor = 1.0
    for i in detect(patient):
        factor *= i.amplify
    return min(factor, 1.8)


def has_conflict(patient: dict) -> bool:
    """True when a treatment for one problem would worsen another."""
    return any(i.kind == "conflict" for i in detect(patient))
