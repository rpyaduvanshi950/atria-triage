"""
The escalation invariant.

ATRIA may escalate on its own. It may never de-escalate on its own. This is the
sentence on the solution slide, made mechanical — and the single property most
worth being able to demonstrate to a judge.

Priority is 1 (most urgent) .. 5 (least), matching ESI, so "escalate" means the
number goes *down*.
"""
from __future__ import annotations

from enum import Enum


class Source(Enum):
    RULE = "layer0_rule"        # deterministic red-flag gate
    MODEL = "layer1_model"      # acuity scorer
    TRAJECTORY = "layer2_trend" # dynamic re-ranker
    HUMAN = "clinician"         # the only source permitted to downgrade


def apply(current: int, proposed: int, source: Source) -> int:
    """
    Fold a proposed priority into the current one.

    Machines ratchet upward in urgency only. Any downgrade requires a clinician,
    who is recorded in the Layer 3 audit log with a signed reason code.
    """
    if not (1 <= current <= 5 and 1 <= proposed <= 5):
        raise ValueError(f"priority out of range: current={current} proposed={proposed}")
    if source is Source.HUMAN:
        return proposed              # nurse authority is absolute
    return min(current, proposed)    # machines escalate, never relent
