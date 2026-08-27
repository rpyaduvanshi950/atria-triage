"""
Layer 2 — the dynamic re-ranker. The differentiator.

Layer 1 asks "how sick does this patient look right now?" from a snapshot taken
once, at the door. Layer 2 asks the question ATRIA exists to answer: "who is
becoming sickest while nobody is looking?"

It consumes repeated vitals as they arrive and reasons over *trajectory*: deltas
across trailing windows, shock index and its trend, and how long someone has been
held. Escalations from here pass through the ratchet, so they can only ever raise
priority.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# Escalation thresholds over the trailing window. Deliberately conservative:
# a false positive costs minutes, a false negative costs a life.
DELTA_RULES = [
    ("o2sat", "drop", 3.0, "SpO2 falling {delta:+.0f}% in {mins:.0f}m"),
    ("sbp", "drop", 15.0, "SBP falling {delta:+.0f} in {mins:.0f}m"),
    ("heartrate", "rise", 20.0, "HR rising {delta:+.0f} in {mins:.0f}m"),
    ("resprate", "rise", 6.0, "RR rising {delta:+.0f} in {mins:.0f}m"),
]

SHOCK_INDEX_ALERT = 0.9          # HR/SBP >= 0.9 is a recognised concern threshold

# Safe waiting time per priority band, in minutes. Breaching forces a re-look —
# a long wait must never be silently absorbed.
# PRD REA-002. Configuration, not UI constants: a site may set its own.
REASSESS_MINUTES = {1: 5, 2: 15, 3: 45, 4: 90, 5: 180}


@dataclass
class Trend:
    stay_id: int
    proposed_band: int | None = None
    reasons: tuple[str, ...] = ()
    shock_index: float | None = None
    overdue_by: float = 0.0
    #: past the safe wait for their band — needs a human re-look, which is not
    #: the same as being sicker
    needs_reassessment: bool = False
    readings: int = 0

    @property
    def escalates(self) -> bool:
        return self.proposed_band is not None

    def as_dict(self) -> dict:
        return dict(proposed_band=self.proposed_band, reasons=list(self.reasons),
                    shock_index=round(self.shock_index, 2) if self.shock_index else None,
                    overdue_by=round(self.overdue_by, 1),
                    needs_reassessment=self.needs_reassessment, readings=self.readings)


def _window(history: pd.DataFrame, now: pd.Timestamp, minutes: int) -> pd.DataFrame:
    return history[history["charttime"] >= now - pd.Timedelta(minutes=minutes)]


def assess(
    history: pd.DataFrame,
    *,
    now: pd.Timestamp,
    current_band: int,
    arrived: pd.Timestamp,
    window_minutes: int = 60,
) -> Trend:
    """
    Evaluate one patient's trajectory. `history` is their vitalsign rows so far.

    Returns a proposed band only when something warrants escalation; the caller
    folds it in through the ratchet, which enforces that this can never lower
    urgency.
    """
    t = Trend(stay_id=int(history["stay_id"].iloc[0]) if len(history) else -1)
    reasons: list[str] = []

    win = _window(history, now, window_minutes).sort_values("charttime")
    t.readings = len(win)

    if len(win) >= 2:
        first, last = win.iloc[0], win.iloc[-1]
        mins = (last["charttime"] - first["charttime"]).total_seconds() / 60 or 1.0

        for col, direction, limit, tmpl in DELTA_RULES:
            a = pd.to_numeric(pd.Series([first[col]]), errors="coerce").iloc[0]
            b = pd.to_numeric(pd.Series([last[col]]), errors="coerce").iloc[0]
            if pd.isna(a) or pd.isna(b):
                continue
            delta = b - a
            hit = (direction == "drop" and delta <= -limit) or (direction == "rise" and delta >= limit)
            if hit:
                reasons.append(tmpl.format(delta=delta, mins=mins))

        hr = pd.to_numeric(pd.Series([last["heartrate"]]), errors="coerce").iloc[0]
        sbp = pd.to_numeric(pd.Series([last["sbp"]]), errors="coerce").iloc[0]
        if pd.notna(hr) and pd.notna(sbp) and sbp > 0:
            t.shock_index = float(hr / sbp)
            if t.shock_index >= SHOCK_INDEX_ALERT:
                reasons.append(f"shock index {t.shock_index:.2f}")

    # Physiology is what escalates: one band per distinct concern, capped at two.
    physiological = list(reasons)
    proposed = current_band
    if physiological:
        proposed = max(1, current_band - min(len(physiological), 2))

    # Queue aging is a separate signal. A long wait does not make a patient
    # sicker, so it does not inflate the band — it forces a human re-look, and
    # only escalates as a safety net once the wait becomes indefensible.
    waited = (now - arrived).total_seconds() / 60
    safe = REASSESS_MINUTES.get(current_band, 120)
    if waited > safe:
        t.overdue_by = waited - safe
        t.needs_reassessment = True
        if waited >= 3 * safe and safe > 0:
            proposed = min(proposed, max(1, current_band - 1))
            reasons.append(
                f"held {waited:.0f}m, {waited / safe:.1f}x the safe wait for band {current_band}")

    if proposed < current_band:
        t.proposed_band = proposed
    t.reasons = tuple(reasons[:3])
    return t
