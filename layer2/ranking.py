"""
Attention ranking — PRD section 11.

Two ideas do the work here.

**Safety bands are strict.** Operational pressure and waiting time may reorder
patients *within* a clinical band; they may never move one across a band
boundary. A busy department does not make a sick patient less sick, and a model
that lets flow pressure quietly downgrade acuity is the failure this whole system
exists to prevent.

The bands are represented explicitly and sorted lexicographically rather than by
adding large numeric offsets. Offsets are the usual trick and they work right up
until someone adds a modifier bigger than the gap; then the invariant fails
silently and nobody notices for a year.

**Attention rank is not ESI.** ESI is a clinical acuity classification the nurse
signs. Rank is a continuously changing sequence. The UI must never use one word
for the other.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Band(IntEnum):
    """Lower is more urgent. Order is the safety guarantee."""

    CRITICAL = 0              # Layer 0 fired — above everything
    DIAGNOSTIC_UNCERTAINTY = 1  # essential vitals missing — above scored ESI 2-5
    ESI_2 = 2
    ESI_3 = 3
    ESI_4 = 4
    ESI_5 = 5

    @classmethod
    def for_patient(cls, *, critical: bool, uncertain: bool, esi: int | None) -> "Band":
        if critical:
            return cls.CRITICAL
        if uncertain:
            return cls.DIAGNOSTIC_UNCERTAINTY
        return {2: cls.ESI_2, 3: cls.ESI_3, 4: cls.ESI_4, 5: cls.ESI_5}.get(
            esi or 5, cls.ESI_5) if (esi or 5) > 1 else cls.CRITICAL


# --- within-band modifiers, PRD 11.2 ---------------------------------------

WORSENING_REPORTED = 140.0
VITALS_RECHECK_DUE = 55.0
FIVE_HOUR_SAFEGUARD = 50.0
FIVE_HOUR_MINUTES = 300.0
RECORD_UNAVAILABLE = 12.0
VITALS_CONNECTION_UNAVAILABLE = 8.0
INFO_GAP_CONNECTED = 4.0
INFO_GAP_DISCONNECTED = 10.0
OPERATIONAL_MAX = 18.0

#: No modifier may reach this. Enforced by test, not by hope.
MODIFIER_CEILING = 500.0


@dataclass
class RankInput:
    stay_id: int
    band: Band
    waited_minutes: float = 0.0
    arrival_sequence: int = 0
    worsening_reported: bool = False
    recheck_due: bool = False
    sepsis_trajectory: bool = False
    record_unavailable: bool = False
    vitals_connection_down: bool = False
    information_gap: bool = False
    systems_connected: bool = True
    operational_pressure: float = 0.0    # 0..1, from the flow forecast


@dataclass
class Ranked:
    stay_id: int
    band: Band
    rank: int
    within_band: float
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return dict(stay_id=self.stay_id, band=self.band.name, band_order=int(self.band),
                    rank=self.rank, within_band=round(self.within_band, 2),
                    reasons=list(self.reasons))


def within_band_score(r: RankInput) -> tuple[float, tuple[str, ...]]:
    """
    Score *inside* one band. Never compared across bands, so its magnitude
    cannot affect clinical ordering.

    Every contribution is recorded as it is applied. Reconstructing an
    explanation afterwards from a final number does not work — you cannot tell
    which of several additions produced it.
    """
    score = 0.0
    why: list[str] = []

    if r.worsening_reported:
        score += WORSENING_REPORTED
        why.append("worsening reported")

    if r.recheck_due:
        score += VITALS_RECHECK_DUE
        why.append("vitals recheck due")

    if r.sepsis_trajectory:
        bump = (r.waited_minutes / 60.0) * 5.0
        score += bump
        why.append(f"sepsis trajectory, waiting {r.waited_minutes:.0f}m")
    elif r.waited_minutes >= FIVE_HOUR_MINUTES:
        score += FIVE_HOUR_SAFEGUARD
        why.append(f"held {r.waited_minutes / 60:.1f}h — five-hour safeguard")

    if r.record_unavailable:
        score += RECORD_UNAVAILABLE
        why.append("record unavailable")
    if r.vitals_connection_down:
        score += VITALS_CONNECTION_UNAVAILABLE
        why.append("vitals feed unavailable — manual verification")
    if r.information_gap:
        gap = INFO_GAP_CONNECTED if r.systems_connected else INFO_GAP_DISCONNECTED
        score += gap
        why.append("known information gap")

    if r.operational_pressure:
        # Bounded, and worded as a planning signal — never as deterioration.
        op = min(OPERATIONAL_MAX, max(0.0, r.operational_pressure) * OPERATIONAL_MAX)
        score += op
        why.append("longer wait under current load")

    return min(score, MODIFIER_CEILING), tuple(why)


def rank_all(patients: list[RankInput]) -> list[Ranked]:
    """
    Order the queue. Band first, always; then within-band score; then longest
    wait, earliest arrival and stable id so the ordering is deterministic and
    the board does not shuffle between identical states.
    """
    scored = []
    for r in patients:
        score, why = within_band_score(r)
        scored.append((r, score, why))

    scored.sort(key=lambda t: (int(t[0].band), -t[1],
                               -t[0].waited_minutes, t[0].arrival_sequence,
                               t[0].stay_id))
    return [Ranked(r.stay_id, r.band, i + 1, score, why)
            for i, (r, score, why) in enumerate(scored)]
