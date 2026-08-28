"""
PRD §21 acceptance scenarios — one test per row, named after the scenario.

These are the build plan §5 acceptance tests. Each asserts against actual
API/DB/engine state, not UI rendering.  Fed from the synthetic fixture pack
(data/synthetic/fixtures.json) plus programmatic synthetic patients.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from data.loaders.synthetic import generate
from layer0.engine import gate, RuleTable
from layer1.model import AcuityScorer
from layer2.ranking import Band, RankInput, rank_all, within_band_score, MODIFIER_CEILING
from layer2.trajectory import REASSESS_MINUTES, CHARGE_NURSE_GRACE_MULTIPLIER, assess
from layer3.audit import AuditLog
from layer3.workflow import BlindAssessmentError, Outcome, Stage, Workflow
from service.clock import build_events
from service.queue import QueueEngine

FIXTURES = json.loads((Path("data/synthetic/fixtures.json")).read_text())
_patients = {p["id"]: p for p in FIXTURES["patients"]}
AV = {"heartrate", "resprate", "o2sat", "sbp", "dbp", "temperature", "age"}


def _fixture(fixture_id: str) -> dict:
    """Pull a named fixture and flatten it into a Layer-0-compatible dict."""
    f = _patients[fixture_id]
    v = f.get("vitals", f.get("vitals_at_arrival", {}))
    return {**v, "age": f.get("age")}


def _seeded_engine(n: int = 12, seed: int = 5, slots: int = 0) -> QueueEngine:
    q = QueueEngine(AcuityScorer().fit(generate(900, seed=3)), slots=slots)
    for e in build_events(generate(n, seed=seed)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    return q


# --- 1. test_pediatric_control ------------------------------------------------

def test_pediatric_control():
    """A 4-year-old's RR 32 and SBP 88 are normal — should NOT fire RF13 or RF03."""
    patient = _fixture("pediatric_control")
    g = gate(patient, AV)
    fired_ids = {r.id for r in g.fired}
    assert "RF13" not in fired_ids, "RR 32 is normal for a 4-year-old"
    assert "RF03" not in fired_ids, "SBP 88 is above paediatric threshold (78)"


# --- 2. test_older_adult_same_vitals ------------------------------------------

def test_older_adult_same_vitals():
    """A 72-year-old with the same vitals SHOULD fire RF13 and RF03."""
    patient = _fixture("older_adult_same_vitals")
    g = gate(patient, AV)
    fired_ids = {r.id for r in g.fired}
    assert "RF13" in fired_ids, "RR 32 exceeds adult upper limit of 30"
    assert "RF03" in fired_ids, "SBP 88 is below adult threshold of 90"


# --- 3. test_missing_essential_data -------------------------------------------

def test_missing_essential_data():
    """RF11 or a red-flag with sparse data: system does not produce a normal ranking.

    The fixture has only 1 vital (SpO₂ 84%), which fires RF02 on its own.
    The engine allows a confirmed red flag to stand even with sparse data —
    'a recorded SpO₂ of 82 does not become uncertain just because the rest of
    the form is blank.' So the system either hard-stops OR fires a critical
    flag; either way it never produces a normal band 3/4/5 ranking.
    """
    patient = _fixture("missing_essential_data")
    g = gate(patient, AV)
    # With only 1 vital recorded, one of two things must be true:
    #   - hard_stop (RF11): insufficient data, no score
    #   - is_red (RF02): the single vital is itself critical
    # In either case, the system never produces a normal confident ranking.
    assert g.hard_stop or g.is_red, \
        "with only 1 vital, system must either hard-stop or flag the critical value"
    assert g.observed_fields < 3, f"expected <3 observed fields, got {g.observed_fields}"


# --- 4. test_low_oxygen -------------------------------------------------------

def test_low_oxygen():
    """SpO₂ 84% → RF02 fires, band 1, red flag."""
    patient = _fixture("low_oxygen")
    g = gate(patient, AV)
    fired_ids = {r.id for r in g.fired}
    assert "RF02" in fired_ids, "SpO₂ 84% must fire RF02"
    assert g.is_red, "should be a confirmed red flag"
    assert g.priority == 1, "confirmed red flag → band 1"


# --- 5. test_adult_rr_boundary ------------------------------------------------

def test_adult_rr_boundary():
    """RR 30 is the edge — should NOT fire. RR 31 SHOULD fire RF13."""
    base = _fixture("adult_rr_boundary")

    at_30 = {**base, "resprate": 30}
    g30 = gate(at_30, AV)
    assert "RF13" not in {r.id for r in g30.fired}, "RR 30 is the edge, not critical"

    at_31 = {**base, "resprate": 31}
    g31 = gate(at_31, AV)
    assert "RF13" in {r.id for r in g31.fired}, "RR 31 exceeds the limit"


# --- 6. test_sepsis_trajectory ------------------------------------------------

def test_sepsis_trajectory():
    """Worsening vitals over time → Layer 2 trajectory escalation."""
    f = _patients["sepsis_trajectory"]
    t0 = pd.Timestamp("2026-08-28 08:00")

    rows = []
    for offset_min, key in [(0, "vitals_at_arrival"), (30, "vitals_at_30_minutes"),
                             (60, "vitals_at_60_minutes")]:
        v = f[key]
        rows.append({**v, "stay_id": f["stay_id"],
                     "charttime": t0 + pd.Timedelta(minutes=offset_min)})
    hist = pd.DataFrame(rows)

    t = assess(hist, now=t0 + pd.Timedelta(minutes=60),
               current_band=3, arrived=t0)
    assert t.escalates, "trajectory should escalate on worsening vitals"
    assert any("HR rising" in r or "SBP falling" in r or "shock index" in r
               for r in t.reasons), f"expected physiological reasons, got {t.reasons}"


# --- 7. test_five_hour_safeguard ----------------------------------------------

def test_five_hour_safeguard():
    """After 300 minutes, the five-hour within-band safeguard fires."""
    r = RankInput(1, Band.ESI_5, waited_minutes=310)
    score, reasons = within_band_score(r)
    assert score > 0, "five-hour safeguard should contribute score"
    assert any("five-hour" in reason or "safeguard" in reason for reason in reasons)
    # The modifier must NOT cross a band boundary
    assert score <= MODIFIER_CEILING


# --- 8. test_blind_assessment -------------------------------------------------

def test_blind_assessment():
    """The recommendation is absent (not hidden) before the nurse commits."""
    a = Workflow().open(1)
    payload = a.visible_to_nurse()
    assert "atria_esi" not in payload, "atria_esi must be absent, not null"
    assert "outcome" not in payload, "outcome must be absent before reveal"
    assert payload["revealed"] is False


# --- 9. test_match ------------------------------------------------------------

def test_match():
    """Nurse and ATRIA agree → outcome is MATCH, no reason required."""
    a = Workflow().open(1)
    a.submit_nurse_esi(3)
    outcome = a.reveal(3)
    assert outcome is Outcome.MATCH
    assert not a.needs_reason


# --- 10. test_nurse_escalation ------------------------------------------------

def test_nurse_escalation():
    """Nurse is more urgent than ATRIA → NURSE_ESCALATION, no reason required."""
    a = Workflow().open(1)
    a.submit_nurse_esi(2)
    outcome = a.reveal(3)
    assert outcome is Outcome.NURSE_ESCALATION
    assert not a.needs_reason


# --- 11. test_nurse_downgrade -------------------------------------------------

def test_nurse_downgrade():
    """Nurse is less urgent than ATRIA → NURSE_DOWNGRADE, reason required."""
    a = Workflow().open(1)
    a.submit_nurse_esi(4)
    outcome = a.reveal(3)
    assert outcome is Outcome.NURSE_DOWNGRADE
    assert a.needs_reason
    with pytest.raises(BlindAssessmentError, match="requires a reason"):
        a.finalise(clinician="n")


# --- 12. test_guardrail_override ----------------------------------------------

def test_guardrail_override():
    """A fired guardrail requires a reason to override. Outcome is GUARDRAIL."""
    a = Workflow().open(1)
    a.submit_nurse_esi(3)
    outcome = a.reveal(1, guardrail=True)
    assert outcome is Outcome.GUARDRAIL
    assert a.needs_reason


# --- 13. test_vitals_due ------------------------------------------------------

def test_vitals_due():
    """Reassessment intervals match the PRD and flag when overdue."""
    assert REASSESS_MINUTES == {1: 5, 2: 15, 3: 45, 4: 90, 5: 180}

    # Simulate a patient held past their safe wait
    hist = pd.DataFrame([{
        "stay_id": 1, "charttime": pd.Timestamp("2026-08-28 08:00"),
        "heartrate": 80, "resprate": 16, "o2sat": 97, "sbp": 120,
        "dbp": 70, "temperature": 37.0,
    }])
    t = assess(hist, now=pd.Timestamp("2026-08-28 09:30"),
               current_band=3, arrived=pd.Timestamp("2026-08-28 08:00"))
    assert t.needs_reassessment, "90 min > 45 min safe wait for band 3"
    assert t.overdue_by > 0


# --- 14. test_worsening_while_waiting -----------------------------------------

def test_worsening_while_waiting():
    """A worsening report clears sign-off and starts a fresh blind cycle."""
    q = _seeded_engine()
    sid = q.snapshot()["rows"][0]["stay_id"]

    q.nurse_assess(sid, 3)
    q.reveal(sid)
    q.finalise(sid, clinician="n", reason_code="clinically_well")
    assert q.workflow.open(sid).stage is Stage.SIGNED

    q.report_change(sid)
    a = q.workflow.open(sid)
    assert a.stage is Stage.AWAITING_NURSE
    assert a.nurse_esi is None, "old ESI must be discarded"
    assert a.atria_esi is None, "old recommendation must be discarded"
    assert a.cycle == 2


# --- 15. test_capacity_full ---------------------------------------------------

def test_capacity_full():
    """When all staffed spaces are occupied, forecast shows surge."""
    from service.forecast import FlowInputs, project
    out = project(FlowInputs(
        waiting=40, inside=20, nurses=4, arrival_rate_per_hour=30,
        physical_spaces=20,
    ))
    # Treatment is capped at staffed spaces
    assert all(p.in_treatment <= out.staffed_spaces for p in out.points)
    # State should be Busy or Surge
    assert out.state in ("Busy", "Surge"), f"expected Busy/Surge, got {out.state}"


# --- 16. test_roster_disconnected ---------------------------------------------

def test_roster_disconnected():
    """Disconnected roster reduces assumed staffing capacity."""
    from service.forecast import FlowInputs, project
    kw = dict(waiting=20, inside=10, nurses=6, arrival_rate_per_hour=12,
              physical_spaces=20)
    connected = project(FlowInputs(**kw))
    degraded = project(FlowInputs(**kw, roster_connected=False))
    assert degraded.staffed_spaces < connected.staffed_spaces
    assert any("roster" in a for a in degraded.assumptions)


# --- 17. test_model_unavailable -----------------------------------------------

def test_model_unavailable():
    """When the model is down, Layer 0 keeps gating. Confidence drops to LOW."""
    q = QueueEngine(AcuityScorer().fit(generate(900, seed=3)), slots=0)
    q.degraded = True
    for e in build_events(generate(8, seed=7)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    snap = q.snapshot()
    assert snap["degraded"]
    # All patients should have LOW confidence (model unavailable)
    for row in snap["rows"]:
        if row["state"] != "IN TREATMENT":
            assert row["confidence"] == "LOW", \
                f"stay {row['stay_id']} has confidence {row['confidence']} while model is down"


# --- 18. test_guardrail_service_down ------------------------------------------

def test_guardrail_service_down():
    """Guardrail service down → fail closed. The orchestrator must refuse to
    produce any recommendation, not fall through to the model.

    This is the asymmetric failure mode from PRD §19.1: guardrail outage is NOT
    the same as model outage. Model down → fail open (Layer 0 still runs).
    Guardrail down → fail closed (nothing runs).

    Tested by simulating the guardrail engine raising an exception; the
    orchestrator must not produce a score.
    """
    from unittest.mock import patch

    q = QueueEngine(AcuityScorer().fit(generate(900, seed=3)), slots=0)
    events = build_events(generate(5, seed=9))

    # Simulate guardrail service being unreachable
    with patch("service.queue.gate", side_effect=RuntimeError("guardrail service unavailable")):
        for e in events:
            if e.kind == "arrival":
                try:
                    q.on_arrival(e)
                except RuntimeError:
                    pass  # fail closed: the arrival is rejected
            else:
                try:
                    q.on_vitals(e)
                except RuntimeError:
                    pass

    # No patients should have been scored — fail closed means nothing gets through
    assert len(q.patients) == 0, \
        "guardrail service down must prevent any patient from being scored"


# --- 19. test_history_ordering ------------------------------------------------

def test_history_ordering():
    """The audit trail is hash-chained and temporally ordered."""
    q = _seeded_engine()
    sid = q.snapshot()["rows"][0]["stay_id"]

    q.nurse_assess(sid, 3)
    q.reveal(sid)
    q.finalise(sid, clinician="n", reason_code="clinically_well")

    intact, note = q.audit.verify()
    assert intact, f"audit chain broken: {note}"

    # Events should be in temporal order
    times = [e.at for e in q.audit]
    assert times == sorted(times), "audit events must be temporally ordered"


# --- 20. test_charge_nurse_escalation (REA-008) --------------------------------

def test_charge_nurse_escalation():
    """REA-008: After the grace period, a charge-nurse escalation event is audited."""
    # Simulate a band-3 patient waiting 2× the safe wait (45 × 2 = 90 min)
    hist = pd.DataFrame([{
        "stay_id": 1, "charttime": pd.Timestamp("2026-08-28 08:00"),
        "heartrate": 80, "resprate": 16, "o2sat": 97, "sbp": 120,
        "dbp": 70, "temperature": 37.0,
    }])
    safe = REASSESS_MINUTES[3]  # 45 min
    grace = safe * CHARGE_NURSE_GRACE_MULTIPLIER  # 90 min

    t = assess(hist, now=pd.Timestamp("2026-08-28 08:00") + pd.Timedelta(minutes=grace + 1),
               current_band=3, arrived=pd.Timestamp("2026-08-28 08:00"))
    assert t.needs_reassessment, "should need reassessment"
    assert t.charge_nurse_alert, "should trigger charge-nurse alert after grace period"
    assert any("REA-008" in r for r in t.reasons), \
        f"expected REA-008 in reasons, got {t.reasons}"


def test_reveal_token_is_required_and_single_use():
    """
    Build plan §6.2 — no token exists until a nurse assessment is durably
    stored, so the ordering is a server invariant rather than something the
    client happens to get right. A stale token from an earlier cycle is refused.
    """
    from fastapi.testclient import TestClient
    import service.app as app_module

    async def _no_replay(*_a, **_kw):
        return None

    original, app_module._replay = app_module._replay, _no_replay
    try:
        with TestClient(app_module.app) as client:
            engine = app_module.engine
            engine.scorer = engine.scorer or AcuityScorer().fit(generate(600, seed=3))
            engine.slots = 0
            for e in build_events(generate(10, seed=5)):
                engine.on_arrival(e) if e.kind == "arrival" else engine.on_vitals(e)

            rows = client.get("/v1/queue").json()["rows"]
            sid = [r for r in rows if r["state"] != "IN TREATMENT"][0]["stay_id"]

            issued = client.post(
                f"/v1/encounters/{sid}/nurse-assessments?esi=3").json()
            token = issued["reveal_token"]
            assert token, "a stored assessment must mint a token"

            wrong = client.post(
                f"/v1/assessments/{sid}/reveal?reveal_token=not-the-token")
            assert wrong.status_code == 409

            ok = client.post(f"/v1/assessments/{sid}/reveal?reveal_token={token}")
            assert ok.status_code == 200 and ok.json()["revealed"] is True

            # a new cycle invalidates the old token
            client.post(f"/v1/encounters/{sid}/worsening")
            stale = client.post(f"/v1/assessments/{sid}/reveal?reveal_token={token}")
            assert stale.status_code == 409
    finally:
        app_module._replay = original


# --- CORS: a port collision must not look like a broken API ------------------

def test_the_local_dev_ports_are_allowed_by_default():
    """
    Next falls back to 3001, 3002... when 3000 is taken. A rejected preflight
    surfaces in the browser as a bare 400 with no explanation, which is a
    miserable thing to debug during a demo.
    """
    import service.app as app_module
    for port in (3000, 3001, 3002):
        assert f"http://localhost:{port}" in app_module.ALLOWED_ORIGINS


def test_cors_is_a_list_not_a_wildcard():
    """This API mutates clinical state; it must not accept a write from anywhere."""
    import service.app as app_module
    assert "*" not in app_module.ALLOWED_ORIGINS

    from fastapi.testclient import TestClient
    with TestClient(app_module.app) as client:
        rejected = client.options(
            "/v1/queue",
            headers={"Origin": "http://somewhere-else.example",
                     "Access-Control-Request-Method": "POST"},
        )
        assert rejected.status_code == 400
