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

# How many patients the bay can treat at once. When a slot frees, the highest
# priority waiting patient is taken through. Without this the queue only ever
# grows, waits climb without bound, and queue aging escalates everyone to band 1
# — which is a property of the simulation, not of the triage logic.
TREATMENT_SLOTS = 3

# Roughly how long treatment takes, by the band they were taken at (minutes).
TREATMENT_MINUTES = {1: 55, 2: 45, 3: 35, 4: 25, 5: 15}
from layer1.model import AcuityScorer
from layer2.ratchet import Source, apply
from layer3.audit import AuditLog
from layer2.trajectory import REASSESS_MINUTES, assess


@dataclass
class Patient:
    stay_id: int
    ticket: str
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
    #: set when a clinician takes them through; they leave the waiting board
    seen_at: pd.Timestamp | None = None
    leaves_at: pd.Timestamp | None = None
    seen_at_band: int | None = None

    def waited(self, now: pd.Timestamp) -> float:
        return max(0.0, (now - self.arrived).total_seconds() / 60)

    def as_dict(self, now: pd.Timestamp) -> dict:
        return dict(
            stay_id=self.stay_id, ticket=self.ticket,
            band=self.band, band_before=self.band_before,
            state="IN TREATMENT" if self.seen_at is not None else self.state,
            red_flag=self.red_flag,
            needs_measurement=self.needs_measurement, confidence=self.confidence,
            reasons=list(self.reasons), missing=list(self.missing),
            risk=round(self.risk, 3), age=self.age, gender=self.gender,
            complaint=self.complaint, waited=round(self.waited(now)),
            overdue_by=round(self.overdue_by), readings=len(self.history),
            signed_off=self.signed_off,
        )


class QueueEngine:
    def __init__(self, scorer: AcuityScorer | None = None, audit: AuditLog | None = None,
                 slots: int = TREATMENT_SLOTS):
        #: treatment capacity. 0 means nobody is ever taken through, which is
        #: what the scenario fixtures want: they exercise triage logic, not
        #: department throughput.
        self.slots = slots
        self.scorer = scorer
        self.audit = audit or AuditLog()
        self.patients: dict[int, Patient] = {}
        self.now: pd.Timestamp | None = None
        self.latencies: list[float] = []
        self.events_log: list[dict] = []
        self.degraded = False
        self.in_treatment: dict[int, Patient] = {}
        self.seen: list[Patient] = []
        self.ticker: list[dict] = []
        self._next_ticket = 1

    # --- ingest ------------------------------------------------------------

    def on_arrival(self, e) -> None:
        t0 = time.perf_counter()
        p = e.payload
        self.now = pd.Timestamp(e.at)

        patient = Patient(
            stay_id=e.stay_id, ticket=f"A-{self._next_ticket:02d}", arrived=self.now,
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
        self._next_ticket += 1
        self.patients[e.stay_id] = patient
        self._advance_service()
        self._tick("arrived", patient, f"{patient.complaint}, band {patient.band}")
        self.audit.append(
            "arrival", patient.stay_id, self.now, band=patient.band,
            confidence=patient.confidence, risk=round(patient.risk, 4),
            red_flag=patient.red_flag, needs_measurement=patient.needs_measurement,
            missing=list(patient.missing), degraded=self.degraded,
        )
        self.latencies.append((time.perf_counter() - t0) * 1000)

    def on_vitals(self, e) -> dict | None:
        t0 = time.perf_counter()
        self.now = pd.Timestamp(e.at)
        self._advance_service()
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
                self._tick("escalated", patient,
                           f"{patient.band_before} to {new} — {t.reasons[0] if t.reasons else ''}")
                self.audit.append(
                    "escalation", patient.stay_id, self.now,
                    frm=patient.band_before, to=new, reasons=list(t.reasons),
                    shock_index=t.shock_index, readings=t.readings, source="layer2_trend",
                )
        self.latencies.append((time.perf_counter() - t0) * 1000)
        return change

    # --- service: patients are actually seen and leave ----------------------

    def _tick(self, kind: str, patient: "Patient", detail: str) -> None:
        self.ticker.append(dict(at=str(self.now)[11:16], kind=kind,
                                ticket=patient.ticket, detail=detail))
        self.ticker = self.ticker[-14:]

    def _advance_service(self) -> None:
        """Discharge finished treatments, then pull the next patients in."""
        if self.now is None:
            return

        for stay_id, p in list(self.in_treatment.items()):
            if p.leaves_at is not None and self.now >= p.leaves_at:
                del self.in_treatment[stay_id]
                self.seen.append(p)
                self._tick("left", p, f"treated, waited {p.waited(p.seen_at):.0f}m")
                self.audit.append("departure", stay_id, self.now,
                                  band=p.seen_at_band,
                                  waited_minutes=round(p.waited(p.seen_at)))

        while len(self.in_treatment) < self.slots and self.patients:
            # highest urgency first, then longest wait — the queue's whole job
            stay_id, p = min(self.patients.items(),
                             key=lambda kv: (kv[1].band, -kv[1].waited(self.now)))
            p.seen_at = self.now
            p.seen_at_band = p.band
            p.leaves_at = self.now + pd.Timedelta(
                minutes=TREATMENT_MINUTES.get(p.band, 30))
            del self.patients[stay_id]
            self.in_treatment[stay_id] = p
            self._tick("seen", p, f"taken through at band {p.band}")
            self.audit.append("seen", stay_id, self.now, band=p.band,
                              waited_minutes=round(p.waited(self.now)))

    # --- output ------------------------------------------------------------

    def snapshot(self) -> dict:
        now = self.now or pd.Timestamp.now()
        # patients being treated stay on the board — a nurse needs to see who is
        # in a bay, not just who is queueing. They sort below everyone waiting.
        rows = ([p.as_dict(now) for p in self.patients.values()]
                + [p.as_dict(now) for p in self.in_treatment.values()])
        rows.sort(key=lambda r: (r["state"] == "IN TREATMENT",
                                 r["state"] != "AWAITING", r["band"], -r["waited"]))
        lat = sorted(self.latencies)
        return dict(
            now=str(now), degraded=self.degraded, rows=rows,
            ticker=list(reversed(self.ticker)),
            in_treatment=len(self.in_treatment), seen=len(self.seen),
            slots=self.slots,
            waiting=len(self.patients),
            escalated=sum(1 for r in rows if r["state"] == "ESCALATED"),
            p95_ms=round(lat[int(len(lat) * 0.95)], 1) if lat else None,
            escalations=self.events_log[-10:],
            audit_entries=len(self.audit),
            audit_intact=self.audit.verify()[0],
        )

    def override(self, stay_id: int, band: int, reason_code: str, clinician: str) -> dict:
        """The only path that may lower urgency. Layer 3 records it."""
        p = self.patients.get(stay_id) or self.in_treatment[stay_id]
        before = p.band
        p.band = apply(p.band, band, Source.HUMAN)
        p.state, p.signed_off = "STABLE", True
        entry = dict(stay_id=stay_id, at=str(self.now), frm=before, to=p.band,
                     reason_code=reason_code, clinician=clinician, kind="override")
        self.events_log.append(entry)
        self.audit.append(
            "override", stay_id, self.now, frm=before, to=p.band,
            reason_code=reason_code, clinician=clinician,
            downgrade=p.band > before, risk=round(p.risk, 4), confidence=p.confidence,
        )
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
