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
from layer1 import pathways

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

# Parallel lanes. One queue works until it does not: as volume grows, the answer
# is not a longer line but more of them, sorted by what each can absorb — the way
# an airport boards by group rather than making everyone queue once.
LANES = {
    "RESUS": (1, 1),        # band 1 only — its own lane, never behind anyone
    "ACUTE": (2, 3),
    "FAST TRACK": (4, 5),
}


def lane_for(band: int) -> str:
    for name, (lo, hi) in LANES.items():
        if lo <= band <= hi:
            return name
    return "FAST TRACK"
from layer1.model import AcuityScorer
from layer2.ratchet import Source, apply
from layer3.audit import AuditLog
from layer3.workflow import BlindAssessmentError, Outcome, Stage, Workflow
from layer2.trajectory import REASSESS_MINUTES, assess
from service import shadow as shadow_mode


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
    #: latest recorded vitals, for the record panel
    vitals: dict = field(default_factory=dict)
    #: RF11/RF12 — the system declined to rank this patient
    abstained: bool = False
    worsening: bool = False
    #: the nurse is part-way through this one, so the queue leaves them alone
    held_for_assessment: bool = False
    abstain_reason: str = ""
    diagnostic_confidence: str = "HIGH"
    #: what ATRIA would have set the band to. Equal to `band` in normal running;
    #: in shadow mode it is the recommendation nobody acted on.
    shadow_band: int | None = None
    pathway: str | None = None
    conflicts: tuple[str, ...] = ()

    def waited(self, now: pd.Timestamp) -> float:
        return max(0.0, (now - self.arrived).total_seconds() / 60)

    def as_dict(self, now: pd.Timestamp) -> dict:
        return dict(
            stay_id=self.stay_id, ticket=self.ticket,
            band=self.band, band_before=self.band_before,
            state="IN TREATMENT" if self.seen_at is not None else self.state,
            lane=lane_for(self.band), abstained=self.abstained,
            held_for_assessment=self.held_for_assessment,
            vitals=dict(self.vitals),
            worsening=self.worsening,
            abstain_reason=self.abstain_reason,
            diagnostic_confidence=self.diagnostic_confidence,
            pathway=self.pathway, conflicts=list(self.conflicts),
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
        #: Stamped on every sign-off. An override recorded six months ago is only
        #: reviewable if the exact model that recommended against it can be named.
        self.model_version = getattr(scorer, "model_version", None) or "untracked"
        #: Shadow mode: every layer runs, nothing acts. See service/shadow.py.
        self.shadow = shadow_mode.ENABLED_BY_DEFAULT
        # `audit or AuditLog()` would be wrong: AuditLog defines __len__, so an
        # empty one is falsy and a caller's durable log would be silently
        # swapped for a fresh in-memory one that writes nothing to disk.
        self.audit = AuditLog() if audit is None else audit
        self.workflow = Workflow()
        self.patients: dict[int, Patient] = {}
        self.now: pd.Timestamp | None = None
        self.latencies: list[float] = []
        self.events_log: list[dict] = []
        self.degraded = False
        self.in_treatment: dict[int, Patient] = {}
        self.seen: list[Patient] = []
        self.ticker: list[dict] = []
        self._next_ticket = 1

    def reset_shift(self) -> None:
        """
        Clear everything that belongs to one shift.

        The demo replay used to clear `patients` and `events_log` by hand and
        leave the other four alone. Stay ids repeat every shift, so a brand new
        patient inherited the previous one's completed assessment and every
        attempt to triage them was refused as "already assessed" — permanently,
        with no way out from the board.

        The audit trail is deliberately NOT cleared. It is the durable record
        and it spans shifts; that is the entire point of it.
        """
        self.patients.clear()
        self.in_treatment.clear()
        self.seen.clear()
        self.events_log.clear()
        self.ticker.clear()
        self.workflow = Workflow()
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
        vitals["shock_index"] = _si(vitals)
        vitals["pulse_pressure"] = _pp(vitals)

        # the three gates, computed before Layer 0 so RF12 can use the spread
        profile = pathways.assess({**vitals, "age": patient.age})

        # Layer 0 first, always. No model can suppress what it fires.
        g = gate({**vitals, "age": patient.age,
                  "_pathway_ambiguity": profile.spread,
                  "_pathway_severity": profile.severity}, AVAILABLE_FIELDS)
        band = 5
        if g.is_red:
            band = apply(band, g.priority, Source.RULE)
            patient.red_flag = g.explain()
            patient.state = "ESCALATED"
        elif g.needs_measurement:
            # not an emergency, but not dismissable either: measure the vital
            band = apply(band, g.priority, Source.RULE)
            patient.needs_measurement = g.explain()

        # RF11 — too little to go on. No score is produced at all: the patient is
        # handed to a clinician rather than given a number nobody should trust.
        if g.hard_stop:
            patient.band = apply(band, g.priority, Source.RULE)
            patient.abstained = True
            patient.abstain_reason = g.explain()
            patient.state = "AWAITING"
            patient.confidence = "LOW"
            patient.reasons = ("no score produced — clinician assessment required",)
            self._next_ticket += 1
            self.patients[e.stay_id] = patient
            self._tick("arrived", patient, "insufficient data — routed to clinician")
            self.audit.append("abstain", patient.stay_id, self.now, rule="RF11",
                              observed_fields=g.observed_fields, reason=g.explain())
            self._advance_service()
            self.latencies.append((time.perf_counter() - t0) * 1000)
            return

        if g.ambiguous:
            patient.abstained = True
            patient.abstain_reason = g.explain()

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
            patient.risk = s.risk
            patient.confidence = s.triage_confidence
            patient.diagnostic_confidence = s.diagnostic_confidence
            patient.reasons, patient.missing = s.reasons, s.missing
            patient.pathway = s.pathways.dominant if s.pathways else None
            patient.conflicts = s.conflicts
        elif self.degraded:
            patient.confidence = "LOW"
            patient.reasons = ("degraded mode — Layer 0 only",)

        patient.vitals = {k: v for k, v in vitals.items() if k in
                          ("heartrate", "sbp", "o2sat", "resprate", "temperature")}
        patient.shadow_band = band
        if self.shadow:
            # Recorded, not acted on. The board shows what the department would
            # have done without ATRIA, so a disagreement is measurable rather
            # than hypothetical.
            band = shadow_mode.baseline_band(patient.red_flag)
            self.audit.append(
                "shadow_recommendation", patient.stay_id, self.now,
                acted_band=band, shadow_band=patient.shadow_band,
                reasons=list(patient.reasons), confidence=patient.confidence,
                red_flag=patient.red_flag, model_version=self.model_version,
                source="layer0_layer1",
            )
        patient.band = band
        if patient.red_flag or band == 1 or patient.abstained:
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
        for k in ("heartrate", "sbp", "o2sat", "resprate", "temperature"):
            latest = _num(e.payload.get(k))
            if latest is not None:
                patient.vitals[k] = latest

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

        # REA-008: charge-nurse escalation after the configurable grace period.
        # A separate audited event, distinct from the recheck flag.
        if t.charge_nurse_alert and not getattr(patient, '_charge_escalated', False):
            patient._charge_escalated = True
            self.audit.append(
                "charge_nurse_escalation", patient.stay_id, self.now,
                band=patient.band, overdue_by=round(t.overdue_by),
                waited_minutes=round(patient.waited(self.now)),
                reason="REA-008 grace period exceeded — charge nurse acknowledgement required",
            )
            self._tick("escalated", patient,
                       f"overdue {t.overdue_by:.0f}m — charge nurse alerted")

        change = None
        if t.escalates and self.shadow:
            proposed = apply(patient.band, t.proposed_band, Source.TRAJECTORY)
            if proposed < patient.band:
                self.audit.append(
                    "shadow_recommendation", patient.stay_id, self.now,
                    acted_band=patient.band, shadow_band=proposed,
                    reasons=list(t.reasons), shock_index=t.shock_index,
                    readings=t.readings, model_version=self.model_version,
                    source="layer2_trend",
                )
            self.latencies.append((time.perf_counter() - t0) * 1000)
            return None

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

        while len(self.in_treatment) < self.slots:
            # A patient the nurse is part-way through assessing is not available
            # to be moved. Taking them through mid-decision destroys the blind
            # cycle they are in, and is wrong in the room too: you do not wheel
            # someone away while they are being triaged.
            available = {k: v for k, v in self.patients.items()
                         if not self.mid_assessment(k)}
            if not available:
                break
            # highest urgency first, then longest wait — the queue's whole job
            stay_id, p = min(available.items(),
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
        for stay_id, p in self.patients.items():
            p.held_for_assessment = self.mid_assessment(stay_id)
        rows = ([p.as_dict(now) for p in self.patients.values()]
                + [p.as_dict(now) for p in self.in_treatment.values()])
        rows.sort(key=lambda r: (r["state"] == "IN TREATMENT",
                                 r["state"] != "AWAITING", r["band"], -r["waited"]))
        lanes = {name: sum(1 for r in rows
                           if r["lane"] == name and r["state"] != "IN TREATMENT")
                 for name in LANES}
        lat = sorted(self.latencies)
        return dict(
            now=str(now), degraded=self.degraded, rows=rows,
            ticker=list(reversed(self.ticker)),
            in_treatment=len(self.in_treatment), seen=len(self.seen),
            slots=self.slots,
            waiting=len(self.patients), lanes=lanes,
            abstained=sum(1 for r in rows if r.get("abstained")),
            escalated=sum(1 for r in rows if r["state"] == "ESCALATED"),
            p95_ms=round(lat[int(len(lat) * 0.95)], 1) if lat else None,
            escalations=self.events_log[-10:],
            audit_entries=len(self.audit),
            audit_intact=self.audit.verify()[0],
        )

    def mid_assessment(self, stay_id: int) -> bool:
        """
        True from the moment the nurse commits to an ESI until they sign off.

        Used to hold a patient in the queue rather than moving them, so the
        decision in progress can be finished.
        """
        a = self.workflow.get(stay_id)
        return bool(a and a.stage is not Stage.SIGNED and a.nurse_esi is not None)

    # --- blind nurse-first assessment (PRD 5.2, 6.1, 10.1) -------------------

    def _on_board(self, stay_id: int):
        """The patient, or None if they have left the board entirely."""
        return self.patients.get(stay_id) or self.in_treatment.get(stay_id)

    def nurse_assess(self, stay_id: int, esi: int) -> dict:
        """
        The nurse commits to an ESI. ATRIA is still hidden at this point.

        Returns a one-time reveal token alongside the stored assessment. The
        token exists only because the assessment was durably recorded, which is
        what makes the ordering a server invariant rather than a convention.
        """
        # Check the patient exists here, not two calls later. Accepting an
        # assessment for somebody who has left the board and then failing at the
        # reveal leaves the nurse having committed to a number for a patient the
        # system cannot show them.
        if self._on_board(stay_id) is None:
            raise BlindAssessmentError(
                f"patient {stay_id} is no longer on the board")
        a = self.workflow.open(stay_id)
        token = a.submit_nurse_esi(esi)
        self.audit.append("nurse_assessment", stay_id, self.now,
                          nurse_esi=esi, cycle=a.cycle, blind=True)
        return {**a.visible_to_nurse(), "reveal_token": token}

    def reveal(self, stay_id: int, token: str | None = None) -> dict:
        """Reveal ATRIA and resolve the comparison. Refuses to run early."""
        a = self.workflow.open(stay_id)
        p = self._on_board(stay_id)
        if p is None:
            # Was a bare KeyError, which escaped the route's handler and became
            # a 500. A patient leaving the board mid-cycle is an ordinary event
            # — a shift rolling over, or them being taken through — and the
            # nurse needs to be told that, not shown a server error.
            raise BlindAssessmentError(
                f"patient {stay_id} left the board before the reveal; "
                f"their assessment was recorded but there is nothing to compare "
                f"against. Pick the next patient.")
        outcome = a.reveal(p.band if not p.abstained else None,
                           abstained=p.abstained, guardrail=bool(p.red_flag),
                           token=token)
        self.audit.append("atria_reveal", stay_id, self.now,
                          nurse_esi=a.nurse_esi, atria_esi=a.atria_esi,
                          outcome=outcome.value, needs_reason=a.needs_reason,
                          abstained=p.abstained, guardrail=bool(p.red_flag))
        return a.visible_to_nurse()

    def finalise(self, stay_id: int, *, clinician: str, reason_code: str = "",
                 reason_note: str = "") -> dict:
        """Sign off. Blocked without a reason where the PRD requires one."""
        a = self.workflow.open(stay_id)
        final = a.finalise(clinician=clinician, reason_code=reason_code,
                           reason_note=reason_note)
        p = self.patients.get(stay_id) or self.in_treatment.get(stay_id)
        if p is not None:
            p.band = apply(p.band, final, Source.HUMAN)
            p.signed_off = True
            p.state = "STABLE"
        self.audit.append("sign_off", stay_id, self.now, final_esi=final,
                          nurse_esi=a.nurse_esi, atria_esi=a.atria_esi,
                          outcome=a.outcome.value if a.outcome else None,
                          reason_code=reason_code, reason_note=a.reason_note,
                          clinician=clinician, cycle=a.cycle,
                          model_version=self.model_version)
        return a.visible_to_nurse()

    def report_change(self, stay_id: int, *, reporter: str = "nurse.demo") -> dict:
        """
        Staff report the patient has worsened.

        This clears any prior sign-off and forces a fresh *blind* cycle. The
        previous ATRIA recommendation is discarded rather than carried over —
        showing it would anchor the very decision that has to stay independent.
        """
        a = self.workflow.open(stay_id)
        a.reopen("worsening reported")
        p = self.patients.get(stay_id) or self.in_treatment.get(stay_id)
        if p is not None:
            p.signed_off = False
            p.state = "AWAITING"
            p.worsening = True
        self.audit.append("worsening_reported", stay_id, self.now,
                          reporter=reporter, cycle=a.cycle,
                          cleared_sign_off=True)
        return a.visible_to_nurse()

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
