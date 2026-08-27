"""
The Harvey-ball decision cue — PRD section 7.1.

A filling circle showing how long this decision has been open. Deliberately
*non-numeric*: a visible countdown turns a clinical judgement into a race, and a
nurse who feels timed makes worse decisions, not faster ones.

Expiry prompts and writes a history event. It never assigns an ESI and never
moves a patient. Nothing clinical happens because a timer ran out.

These are human-factors defaults for a prototype, not clinical standards. They
must be validated by usability testing and made site-configurable.
"""
from __future__ import annotations

BASELINE = {"Steady": 90, "Busy": 105, "Surge": 120}
HIGH_ACUITY_BONUS = -15      # a sicker patient deserves a faster look
AGE_EXTREME_BONUS = 15       # the very young and very old take longer to assess
LOWER_BOUND, UPPER_BOUND = 75, 135


def seconds_for(*, flow_state: str = "Steady", esi: int | None = None,
                age: float | None = None) -> int:
    """How long this decision window should run, in seconds."""
    window = BASELINE.get(flow_state, BASELINE["Steady"])
    if esi is not None and esi <= 2:
        window += HIGH_ACUITY_BONUS
    if age is not None and (age < 12 or age >= 75):
        window += AGE_EXTREME_BONUS
    return max(LOWER_BOUND, min(UPPER_BOUND, window))


def fill_fraction(elapsed_seconds: float, window_seconds: int) -> float:
    """0.0 to 1.0 — how much of the circle is filled."""
    if window_seconds <= 0:
        return 1.0
    return max(0.0, min(1.0, elapsed_seconds / window_seconds))


def expired(elapsed_seconds: float, window_seconds: int) -> bool:
    return elapsed_seconds >= window_seconds
