"""The PRD's hard constraints, as executable checks."""
import pytest

import data.loaders as L
from data.loaders.synthetic import generate
from layer1 import features
from layer1.model import AcuityScorer
from layer3.workflow import BlindAssessmentError, Outcome, Stage, Workflow
from layer2.ranking import Band, RankInput, MODIFIER_CEILING, rank_all, within_band_score
from service import decision_window, fhir, forecast
from service.clock import build_events
from service.queue import QueueEngine


# --- 1 & 2: prohibited model inputs (PRD 14.2, 14.3) ------------------------

def test_the_nurse_esi_is_not_a_model_feature():
    """A model that reads the nurse's answer cannot meaningfully disagree with it."""
    X = features.build(generate(200, seed=1))
    assert "esi" not in X.columns


def test_race_is_not_a_model_feature():
    X = features.build(generate(200, seed=1))
    for banned in features.PROHIBITED:
        assert banned not in X.columns


def test_sex_is_retained_because_it_is_physiological():
    ds = generate(200, seed=1)
    assert ds.edstays["gender"].notna().any()


def test_the_esi_leak_is_available_only_for_measurement():
    """We keep the switch so the cost of compliance can be quantified, not hidden."""
    X = features.build(generate(200, seed=1), leak_nurse_esi=True)
    assert "esi" in X.columns


# --- 3, 4, 5: blind nurse-first workflow ------------------------------------

def test_atria_is_absent_from_the_payload_before_the_nurse_chooses():
    a = Workflow().open(1)
    payload = a.visible_to_nurse()
    assert "atria_esi" not in payload
    assert payload["revealed"] is False


def test_reveal_is_refused_before_the_nurse_commits():
    with pytest.raises(BlindAssessmentError, match="before the nurse"):
        Workflow().open(1).reveal(2)


@pytest.mark.parametrize("nurse,atria,kw,expected", [
    (3, 3, {}, Outcome.MATCH),
    (2, 3, {}, Outcome.NURSE_ESCALATION),
    (3, 2, {}, Outcome.NURSE_DOWNGRADE),
    (3, None, {"abstained": True}, Outcome.UNCERTAIN),
    (3, 1, {"guardrail": True}, Outcome.GUARDRAIL),
])
def test_the_comparison_matrix(nurse, atria, kw, expected):
    a = Workflow().open(1)
    a.submit_nurse_esi(nurse)
    assert a.reveal(atria, **kw) is expected


def test_escalating_needs_no_reason_but_downgrading_does():
    up = Workflow().open(1); up.submit_nurse_esi(2); up.reveal(3)
    assert not up.needs_reason
    assert up.finalise(clinician="n") == 2

    down = Workflow().open(2); down.submit_nurse_esi(3); down.reveal(2)
    assert down.needs_reason
    with pytest.raises(BlindAssessmentError, match="requires a reason"):
        down.finalise(clinician="n")


def test_reporting_change_clears_sign_off_and_discards_the_old_recommendation():
    a = Workflow().open(1)
    a.submit_nurse_esi(3); a.reveal(3); a.finalise(clinician="n")
    assert a.stage is Stage.SIGNED

    a.reopen("worsening reported")
    assert a.stage is Stage.AWAITING_NURSE
    assert a.nurse_esi is None and a.atria_esi is None
    assert a.cycle == 2
    assert "atria_esi" not in a.visible_to_nurse()


def test_the_engine_runs_a_full_blind_cycle_with_audit():
    q = QueueEngine(AcuityScorer().fit(generate(900, seed=3)), slots=0)
    for e in build_events(generate(12, seed=5)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    sid = q.snapshot()["rows"][0]["stay_id"]

    with pytest.raises(BlindAssessmentError):
        q.reveal(sid)
    q.nurse_assess(sid, 4)
    q.reveal(sid)
    q.finalise(sid, clinician="n", reason_code="clinically_well")
    q.report_change(sid)

    kinds = {e.kind for e in q.audit}
    assert {"nurse_assessment", "atria_reveal", "sign_off", "worsening_reported"} <= kinds
    assert q.audit.verify()[0]


# --- 6 & 7: rules and thresholds --------------------------------------------

def test_adult_respiratory_rate_boundaries():
    from layer0.engine import gate
    av = {"heartrate", "resprate", "o2sat", "sbp", "dbp", "temperature", "age"}
    well = dict(age=40, o2sat=98, sbp=124, heartrate=76, temperature=98.6)

    def fired(rr):
        return "RF13" in {r.id for r in gate({**well, "resprate": rr}, av).fired}

    assert fired(31) and not fired(30)      # PRD: >30 critical
    assert fired(9) and not fired(10)       # PRD: <10 critical


def test_respiratory_rate_is_age_banded():
    from layer0.engine import gate
    av = {"heartrate", "resprate", "o2sat", "sbp", "dbp", "temperature", "age"}
    toddler = dict(age=3, o2sat=98, sbp=95, heartrate=120, temperature=98.6)
    assert "RF13" not in {r.id for r in gate({**toddler, "resprate": 32}, av).fired}
    assert "RF13" in {r.id for r in gate({**toddler, "resprate": 40}, av).fired}


def test_reassessment_intervals_match_the_prd():
    from layer2.trajectory import REASSESS_MINUTES
    assert REASSESS_MINUTES == {1: 5, 2: 15, 3: 45, 4: 90, 5: 180}


# --- 11 & 12: safety bands --------------------------------------------------

def test_no_modifier_can_move_a_patient_across_a_band():
    """The invariant. A maximally boosted band always sits below a quiet one above it."""
    loud = RankInput(1, Band.ESI_3, waited_minutes=6000, worsening_reported=True,
                     recheck_due=True, record_unavailable=True,
                     vitals_connection_down=True, information_gap=True,
                     systems_connected=False, operational_pressure=1.0)
    quiet = RankInput(2, Band.ESI_2)
    ranked = {r.stay_id: r.rank for r in rank_all([loud, quiet])}
    assert ranked[2] < ranked[1]


def test_every_modifier_combination_stays_under_the_ceiling():
    worst = RankInput(1, Band.ESI_5, waited_minutes=100000, worsening_reported=True,
                      recheck_due=True, sepsis_trajectory=True,
                      record_unavailable=True, vitals_connection_down=True,
                      information_gap=True, systems_connected=False,
                      operational_pressure=5.0)
    assert within_band_score(worst)[0] <= MODIFIER_CEILING


def test_critical_and_uncertainty_outrank_every_scored_band():
    entries = [RankInput(i, b) for i, b in enumerate(
        [Band.ESI_5, Band.ESI_2, Band.DIAGNOSTIC_UNCERTAINTY, Band.CRITICAL])]
    order = [r.band for r in rank_all(entries)]
    assert order[0] is Band.CRITICAL
    assert order[1] is Band.DIAGNOSTIC_UNCERTAINTY


def test_ranking_is_deterministic():
    a = [RankInput(i, Band.ESI_3, waited_minutes=10) for i in range(5)]
    assert [r.stay_id for r in rank_all(a)] == [r.stay_id for r in rank_all(a)]


def test_every_rank_carries_its_reasons():
    r = rank_all([RankInput(1, Band.ESI_3, worsening_reported=True, recheck_due=True)])[0]
    assert "worsening reported" in r.reasons and "vitals recheck due" in r.reasons


# --- 9 & 10: forecast and decision window -----------------------------------

def test_treatment_is_capped_at_staffed_spaces_but_waiting_is_not():
    out = forecast.project(forecast.FlowInputs(
        waiting=60, inside=18, nurses=4, arrival_rate_per_hour=40, physical_spaces=20))
    assert all(p.in_treatment <= out.staffed_spaces for p in out.points)
    assert max(p.waiting for p in out.points) > out.staffed_spaces


def test_a_disconnected_roster_reduces_assumed_capacity():
    kw = dict(waiting=20, inside=10, nurses=6, arrival_rate_per_hour=12,
              physical_spaces=20)
    connected = forecast.project(forecast.FlowInputs(**kw))
    degraded = forecast.project(forecast.FlowInputs(**kw, roster_connected=False))
    assert degraded.staffed_spaces < connected.staffed_spaces
    assert any("roster" in a for a in degraded.assumptions)


def test_the_forecast_explains_itself_in_a_sentence():
    out = forecast.project(forecast.FlowInputs(
        waiting=30, inside=18, nurses=6, arrival_rate_per_hour=20, physical_spaces=18))
    assert out.explanation.endswith(".") and len(out.explanation.split()) > 6


def test_the_decision_window_stays_inside_its_bounds():
    for state in ("Steady", "Busy", "Surge"):
        for esi in range(1, 6):
            for age in (2, 40, 90):
                assert 75 <= decision_window.seconds_for(
                    flow_state=state, esi=esi, age=age) <= 135


def test_a_sicker_patient_gets_a_shorter_window_and_the_very_young_a_longer_one():
    base = decision_window.seconds_for(flow_state="Steady", esi=3, age=40)
    assert decision_window.seconds_for(flow_state="Steady", esi=2, age=40) < base
    assert decision_window.seconds_for(flow_state="Steady", esi=3, age=3) > base


# --- 14: FHIR ---------------------------------------------------------------

def test_an_absent_vital_is_exported_as_absent_never_as_normal():
    r = fhir.observation(1, "o2sat", None, "2026-08-27T09:00:00Z")
    assert "valueQuantity" not in r
    assert r["dataAbsentReason"]["coding"][0]["code"] == "not-performed"
    assert r["status"] == "registered"


def test_a_recorded_vital_carries_loinc_and_units():
    r = fhir.observation(1, "sbp", 96, "2026-08-27T09:00:00Z")
    assert r["code"]["coding"][0]["code"] == "8480-6"
    assert r["valueQuantity"]["value"] == 96
    assert r["status"] == "final"


def test_the_recommendation_is_not_exported_as_a_clinical_finding_by_default():
    assert "governance review required" in fhir.RESOURCE_MAP["assessment output"]


# --- deployment: session state outlives a code deploy ------------------------

def test_a_fresh_engine_has_everything_the_ui_reads():
    """
    Streamlit Cloud pulls new code and reruns, but st.session_state keeps the
    objects the *previous* version built. The app detects that by checking these
    attributes directly, so this test is what stops the check going stale.
    """
    required = ("workflow", "audit", "in_treatment", "ticker", "patients",
                "seen", "latencies", "degraded", "slots")
    engine = QueueEngine(AcuityScorer().fit(generate(600, seed=3)), slots=3)
    missing = [a for a in required if not hasattr(engine, a)]
    assert not missing, f"engine is missing {missing}"


def test_every_engine_read_in_the_app_goes_through_the_guard():
    """
    board() is a fragment, and fragments rerun without re-executing the module.
    A staleness check in the script body is therefore never reached on the
    reruns that matter — which is exactly how the first fix for this failed.
    Every read must go through engine(), which validates each time.
    """
    import re
    src = open("streamlit_app.py").read()
    # everything after the accessor's own body must go through engine()
    after_accessor = src.split("def init(", 1)[1]
    direct = [ln.strip() for ln in after_accessor.splitlines()
              if "st.session_state.engine" in ln
              and not ln.strip().startswith("#")]
    assert not direct, f"engine read without validating: {direct}"


def test_the_streamlit_app_lists_the_attributes_it_depends_on():
    import re
    src = open("streamlit_app.py").read()
    declared = set(re.findall(r'REQUIRED_ENGINE_ATTRS = \(([^)]*)\)', src)[0]
                   .replace('"', "").replace("'", "").split(", "))
    declared = {d.strip() for d in declared if d.strip()}
    engine = QueueEngine(AcuityScorer().fit(generate(600, seed=3)), slots=0)
    for attr in declared:
        assert hasattr(engine, attr), f"app expects engine.{attr}, which does not exist"


# --- double-submit: Streamlit replays widget state on fragment reruns --------

def test_finalising_twice_is_refused_not_silently_repeated():
    """
    A button handler can fire twice for one click when a fragment reruns. The
    engine must reject the second call rather than double-signing — and the UI
    must not be the only thing standing between a stale click and a corrupt
    audit trail.
    """
    from layer3.workflow import Stage
    q = QueueEngine(AcuityScorer().fit(generate(600, seed=3)), slots=0)
    for e in build_events(generate(10, seed=5)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    sid = q.snapshot()["rows"][0]["stay_id"]

    q.nurse_assess(sid, 3)
    q.reveal(sid)
    q.finalise(sid, clinician="n", reason_code="clinically_well")
    assert q.workflow.open(sid).stage is Stage.SIGNED

    before = len(q.audit)
    with pytest.raises(BlindAssessmentError, match="cannot finalise from signed"):
        q.finalise(sid, clinician="n", reason_code="clinically_well")
    assert len(q.audit) == before, "a refused transition must not write to the log"


def test_the_nurse_may_change_their_mind_before_reveal_but_not_after():
    """
    PRD ASS-006 — changing ESI before sign-off is allowed, and returns to blind
    selection. What is refused is revising the answer once ATRIA has been seen,
    because at that point the choice is no longer independent.
    """
    q = QueueEngine(AcuityScorer().fit(generate(600, seed=3)), slots=0)
    for e in build_events(generate(10, seed=5)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    sid = q.snapshot()["rows"][0]["stay_id"]

    q.nurse_assess(sid, 3)
    q.nurse_assess(sid, 4)                       # allowed: still blind
    assert q.workflow.open(sid).nurse_esi == 4

    q.reveal(sid)
    with pytest.raises(BlindAssessmentError, match="already at"):
        q.nurse_assess(sid, 2)                   # refused: ATRIA has been seen


def test_the_app_gates_every_transition_on_the_current_stage():
    """Each engine call in the UI is guarded, so a replayed click cannot reach it."""
    src = open("streamlit_app.py").read()
    for call in ("eng.nurse_assess", "eng.finalise"):
        idx = src.index(call)
        window = src[max(0, idx - 220):idx]
        assert "a.stage is" in window, f"{call} is not gated on the workflow stage"
    assert "def act(" in src, "transitions must run through the act() guard"


def test_reruns_fall_back_when_fragment_scope_is_illegal():
    """
    st.rerun(scope="fragment") is only legal during a fragment rerun. A click
    landing on a full script run — after any sidebar change — raises instead, so
    every redraw goes through refresh(), which falls back.
    """
    src = open("streamlit_app.py").read()
    assert "def refresh(" in src
    body = src.split("def refresh(", 1)[1].split("def act(", 1)[0]
    assert "StreamlitAPIException" in body and "st.rerun()" in body
    after = src.split("def act(", 1)[1]
    assert 'st.rerun(scope="fragment")' not in after, \
        "call refresh() rather than scoping a rerun directly"


# --- the blind guarantee holds over HTTP, not just in Python -----------------

def test_the_api_never_sends_a_recommendation_before_the_nurse_commits():
    """
    The Next.js client cannot leak what it is never sent. That is why the guard
    lives on the server: a field hidden in a browser is one devtools panel away
    from being visible, but an absent field is absent.
    """
    from fastapi.testclient import TestClient
    import service.app as app_module

    # The startup task clears the engine and replays a shift on a timer. Both
    # would make this test flaky, so it is stubbed and the queue seeded directly.
    async def _no_replay(*_a, **_kw):
        return None

    original = app_module._replay
    app_module._replay = _no_replay
    try:
        with TestClient(app_module.app) as client:
            engine = app_module.engine
            engine.scorer = engine.scorer or AcuityScorer().fit(generate(600, seed=3))
            engine.slots = 0
            for e in build_events(generate(10, seed=5)):
                engine.on_arrival(e) if e.kind == "arrival" else engine.on_vitals(e)
            _assert_blind_over_http(client, engine)
    finally:
        app_module._replay = original


def _assert_blind_over_http(client, engine) -> None:
    rows = client.get("/v1/queue").json()["rows"]
    waiting = [r for r in rows if r["state"] != "IN TREATMENT"]
    assert waiting, "seeding failed"
    sid = waiting[0]["stay_id"]

    early = client.post(f"/v1/assessments/{sid}/reveal")
    assert early.status_code == 409

    blind = client.post(f"/v1/encounters/{sid}/nurse-assessments?esi=3").json()
    assert "atria_esi" not in blind
    assert "outcome" not in blind
    assert blind["revealed"] is False

    revealed = client.post(f"/v1/assessments/{sid}/reveal").json()
    assert revealed["revealed"] is True
    assert "outcome" in revealed



def test_cors_names_its_origins_rather_than_wildcarding():
    """This API mutates clinical state; it must not accept a write from anywhere."""
    import service.app as app_module
    assert "*" not in app_module.ALLOWED_ORIGINS
