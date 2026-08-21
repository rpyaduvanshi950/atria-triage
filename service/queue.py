"""
The queue engine — where the four layers meet.

Holds live patient state, applies Layer 0 on arrival, Layer 1 for a score, and
Layer 2 on every new reading. Every priority change goes through the ratchet, so
the escalate-only invariant holds by construction rather than by discipline.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import pandas as pd

from contracts.schema import VITAL_FIELDS
from layer0.engine import gate

# What the contract can actually supply. GCS and the witnessed-event flags
# (seizure, airway, haemorrhage...) are not columns in any of our sources, so
# their rules are reported as not evaluable rather than fired on assumption.
AVAILABLE_FIELDS = {*VITAL_FIELDS, "age"}
from layer1.model import AcuityScorer
from layer2.ratchet import Source, apply
from layer2.trajectory import REASSESS_MINUTES, assess


@dataclass
class Patient:
    stay_id: int
    arrived: pd.Timestamp
    age: float | None
    gender: str | None
    complaint: str
    band: int = 5
    band_before: int | None = None
    state: str = "STABLE"                 # STABLE | ESCALATED | AWAITING
    red_flag: str | None = None
    needs_measurement: str | None = None
    confidence: str = "MODERATE"
    reasons: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    risk: float = 0.0
    history: list[dict] = field(default_factory=list)
    signed_off: bool = False
    overdue_by: float = 0.0

    def waited(self, now: pd.Timestamp) -> float:
        return max(0.0, (now - self.arrived).total_seconds() / 60)

    def as_dict(self, now: pd.Timestamp) -> dict:
        return dict(
            stay_id=self.stay_id, band=self.band, band_before=self.band_before,
            state=self.state, red_flag=self.red_flag,
            needs_measurement=self.needs_measurement, confidence=self.confidence,
            reasons=list(self.reasons), missing=list(self.missing),
            risk=round(self.risk, 3), age=self.age, gender=self.gender,
            complaint=self.complaint, waited=round(self.waited(now)),
            overdue_by=round(self.overdue_by), readings=len(self.history),
            signed_off=self.signed_off,
        )


class QueueEngine:
    def __init__(self, scorer: AcuityScorer | None = None):
        self.scorer = scorer
        self.patients: dict[int, Patient] = {}
        self.now: pd.Timestamp | None = None
        self.latencies: list[float] = []
        self.events_log: list[dict] = []
        self.degraded = False

    # --- ingest ------------------------------------------------------------

    def on_arrival(self, e) -> None:
        t0 = time.perf_counter()
        p = e.payload
        self.now = pd.Timestamp(e.at)

        patient = Patient(
            stay_id=e.stay_id, arrived=self.now,
            age=_num(p.get("age")), gender=p.get("gender"),
            complaint=str(p.get("chiefcomplaint") or "unspecified"),
        )

        vitals = {k: _num(p.get(k)) for k in
                  ("heartrate", "resprate", "o2sat", "sbp", "dbp", "temperature")}

        # Layer 0 first, always. No model can suppress what it fires.
        g = gate({**vitals, "age": patient.age}, AVAILABLE_FIELDS)
        band = 5
        if g.is_red:
            band = apply(band, g.priority, Source.RULE)
            patient.red_flag = g.explain()
            patient.state = "ESCALATED"
        elif g.needs_measurement:
            # not an emergency, but not dismissable either: measure the vital
            band = apply(band, g.priority, Source.RULE)
            patient.needs_measurement = g.explain()

        # Layer 1 recommends
        if self.scorer is not None and not self.degraded:
            row = {**vitals, "pain": _num(p.get("pain")), "age": patient.age,
                   "shock_index": _si(vitals), "pulse_pressure": _pp(vitals),
                   "is_paediatric": 1.0 if (patient.age or 99) < 15 else 0.0,
                   "is_geriatric": 1.0 if (patient.age or 0) > 60 else 0.0,
                   "arrived_by_ambulance": int("ambul" in str(p.get("arrival_transport", "")).lower())}
            for c in ("heartrate", "resprate", "o2sat", "sbp", "dbp", "temperature"):
                row[f"{c}_missing"] = int(row.get(c) is None or pd.isna(row.get(c)))
            row["n_vitals_missing"] = sum(row[f"{c}_missing"] for c in
                                          ("heartrate", "resprate", "o2sat", "sbp", "dbp", "temperature"))
            s = self.scorer.score_one(row)
            band = apply(band, s.band, Source.MODEL)
            patient.risk, patient.confidence = s.risk, s.confidence
            patient.reasons, patient.missing = s.reasons, s.missing
        elif self.degraded:
            patient.confidence = "LOW"
            patient.reasons = ("degraded mode — Layer 0 only",)

        patient.band = band
        if patient.red_flag or band == 1:
            patient.state = "AWAITING"
        self.patients[e.stay_id] = patient
        self.latencies.append((time.perf_counter() - t0) * 1000)

    def on_vitals(self, e) -> dict | None:
        t0 = time.perf_counter()
        self.now = pd.Timestamp(e.at)
        patient = self.patients.get(e.stay_id)
        if patient is None:
            return None
        patient.history.append(e.payload)

        if self.degraded:
            g = gate({k: _num(e.payload.get(k)) for k in
                      ("heartrate", "resprate", "o2sat", "sbp", "dbp", "temperature")},
                     AVAILABLE_FIELDS)
            if g.is_red and patient.band > 1:
                patient.band_before, patient.band = patient.band, 1
                patient.state, patient.red_flag = "ESCALATED", g.explain()
            self.latencies.append((time.perf_counter() - t0) * 1000)
            return None

        hist = pd.DataFrame(patient.history)
        t = assess(hist, now=self.now, current_band=patient.band, arrived=patient.arrived)
        patient.overdue_by = t.overdue_by
        if t.needs_reassessment and patient.state == "STABLE":
            patient.state = "AWAITING"

        change = None
        if t.escalates:
            new = apply(patient.band, t.proposed_band, Source.TRAJECTORY)
            if new < patient.band:
                patient.band_before = patient.band
                patient.band = new
                patient.state = "ESCALATED"
                patient.reasons = t.reasons
                patient.signed_off = False
                change = dict(stay_id=patient.stay_id, at=str(self.now),
                              frm=patient.band_before, to=new, reasons=list(t.reasons))
                self.events_log.append(change)
        self.latencies.append((time.perf_counter() - t0) * 1000)
        return change

    # --- output ------------------------------------------------------------

    def snapshot(self) -> dict:
        now = self.now or pd.Timestamp.now()
        rows = [p.as_dict(now) for p in self.patients.values()]
        # AWAITING first, then by band, then longest wait
        rows.sort(key=lambda r: (r["state"] != "AWAITING", r["band"], -r["waited"]))
        lat = sorted(self.latencies)
        return dict(
            now=str(now), degraded=self.degraded, rows=rows,
            waiting=len(rows),
            escalated=sum(1 for r in rows if r["state"] == "ESCALATED"),
            p95_ms=round(lat[int(len(lat) * 0.95)], 1) if lat else None,
            escalations=self.events_log[-10:],
        )

    def override(self, stay_id: int, band: int, reason_code: str, clinician: str) -> dict:
        """The only path that may lower urgency. Layer 3 records it."""
        p = self.patients[stay_id]
        before = p.band
        p.band = apply(p.band, band, Source.HUMAN)
        p.state, p.signed_off = "STABLE", True
        entry = dict(stay_id=stay_id, at=str(self.now), frm=before, to=p.band,
                     reason_code=reason_code, clinician=clinician, kind="override")
        self.events_log.append(entry)
        return entry


def _num(v):
    try:
        f = float(v)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _si(v):
    hr, sbp = v.get("heartrate"), v.get("sbp")
    return hr / sbp if hr and sbp else None


def _pp(v):
    sbp, dbp = v.get("sbp"), v.get("dbp")
    return sbp - dbp if sbp and dbp else None
