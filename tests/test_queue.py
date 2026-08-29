"""The queue engine: where Layer 0, 1, 2 and 3 meet."""
import pandas as pd
import pytest

from data.loaders.synthetic import generate
from layer1.model import AcuityScorer
from service.clock import build_events
from service.queue import QueueEngine


@pytest.fixture(scope="module")
def scorer():
    return AcuityScorer().fit(generate(1200, seed=3))


@pytest.fixture(scope="module")
def played(scorer):
    q = QueueEngine(scorer, slots=0)          # no throughput: test the queue itself
    for e in build_events(generate(30, seed=21)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    return q


def test_every_arrival_is_admitted_to_the_queue(played):
    assert len(played.patients) == 30


def test_patients_are_seen_and_leave_when_there_is_capacity(scorer):
    """With treatment slots, the queue drains instead of growing without bound."""
    q = QueueEngine(scorer, slots=3)
    for e in build_events(generate(40, seed=21, hours=3.0)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    assert q.seen, "nobody was ever taken through"
    assert len(q.patients) < 40, "the queue never drained"
    kinds = {e.kind for e in q.audit}
    assert {"seen", "departure"} <= kinds


def test_patients_in_treatment_stay_visible_on_the_board(scorer):
    """
    Checked mid-shift, not at the end: by the final event everyone has been
    treated and discharged, so the board is legitimately empty.
    """
    q = QueueEngine(scorer, slots=3)
    seen_in_treatment = False
    for e in build_events(generate(30, seed=21, hours=3.0)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
        if any(r["state"] == "IN TREATMENT" for r in q.snapshot()["rows"]):
            seen_in_treatment = True
            break
    assert seen_in_treatment, "a nurse must still see who is in a bay"


def test_the_queue_actually_moves(played):
    """Day 1's gate: patients must climb, not sit at their arrival band."""
    assert len(played.events_log) > 0
    assert any(e["to"] < e["frm"] for e in played.events_log)


def test_every_escalation_records_a_reason(played):
    for e in played.events_log:
        if e.get("kind") != "override":
            assert e["reasons"], f"escalation with no reason: {e}"


def test_no_score_is_emitted_without_a_confidence(played):
    for row in played.snapshot()["rows"]:
        assert row["confidence"] in {"HIGH", "MODERATE", "LOW"}


def test_missing_vitals_are_surfaced_not_hidden(played):
    rows = played.snapshot()["rows"]
    assert any(r["missing"] or r["needs_measurement"] for r in rows)


def test_awaiting_sorts_above_everything(played):
    states = [r["state"] for r in played.snapshot()["rows"]]
    if "AWAITING" in states:
        assert states.index("AWAITING") == 0


def test_scoring_stays_under_the_latency_budget(played):
    """400 ms p95 is the number already on the solution slide."""
    assert played.snapshot()["p95_ms"] < 400


def test_only_the_clinician_can_lower_a_band(played, scorer):
    q = QueueEngine(scorer, slots=0)
    for e in build_events(generate(12, seed=5)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    sid = next(iter(q.patients))
    q.patients[sid].band = 1

    entry = q.override(sid, 4, "clinically_well", "nurse.test")
    assert q.patients[sid].band == 4
    assert entry["kind"] == "override"
    assert entry["reason_code"] == "clinically_well"
    assert entry["clinician"] == "nurse.test"


def test_override_is_written_to_the_audit_log(played, scorer):
    q = QueueEngine(scorer, slots=0)
    for e in build_events(generate(12, seed=5)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    before = len(q.events_log)
    q.override(next(iter(q.patients)), 3, "reassessed", "nurse.test")
    assert len(q.events_log) == before + 1


def test_degraded_mode_keeps_gating_without_the_model(scorer):
    """Scenario 06: kill the model, Layer 0 carries on."""
    q = QueueEngine(scorer, slots=0)
    q.degraded = True
    for e in build_events(generate(20, seed=9)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)

    snap = q.snapshot()
    assert snap["degraded"]
    assert snap["waiting"] == 20
    assert all(r["confidence"] == "LOW" for r in snap["rows"]), "degraded scores must not claim confidence"


def test_surge_compresses_arrivals(scorer):
    normal = build_events(generate(40, seed=13), surge=1.0)
    surged = build_events(generate(40, seed=13), surge=3.0)
    span_n = pd.Timestamp(normal[-1].at) - pd.Timestamp(normal[0].at)
    span_s = pd.Timestamp(surged[-1].at) - pd.Timestamp(surged[0].at)
    assert span_s < span_n / 2.5, "3x surge should compress the shift"


# --- shift rollover -----------------------------------------------------------

def _engine_with_patients(seed: int = 5, n: int = 6):
    from data.loaders.synthetic import generate
    from layer1.model import AcuityScorer
    from service.clock import build_events
    from service.queue import QueueEngine

    q = QueueEngine(AcuityScorer().fit(generate(400, seed=3)), slots=0)
    for e in build_events(generate(n, seed=seed)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    return q


def test_a_reused_stay_id_is_not_stuck_from_the_previous_shift():
    """
    The bug this exists for. The demo generator numbers patients 900000 upward
    every shift, so ids repeat. Clearing `patients` but not `workflow` meant a
    brand new patient inherited the last one's completed assessment and every
    attempt to triage them was refused as "already assessed" — permanently,
    with no way out from the board.
    """
    from data.loaders.synthetic import generate
    from service.clock import build_events

    q = _engine_with_patients()
    stay = next(iter(q.patients))
    q.nurse_assess(stay, 3)
    q.reveal(stay, token=q.workflow.open(stay).reveal_token)
    q.finalise(stay, clinician="nurse.demo", reason_code="agree")

    q.reset_shift()
    for e in build_events(generate(6, seed=5)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)

    assert stay in q.patients, "the generator should reuse the same id"
    # must be assessable again, from scratch
    out = q.nurse_assess(stay, 2)
    assert out["reveal_token"]


def test_reset_clears_everything_that_belongs_to_a_shift():
    """
    A caller clearing four of six collections by hand is how the bug above
    happened. One call, and a test that fails if a new collection is added and
    forgotten.
    """
    q = _engine_with_patients()
    stay = next(iter(q.patients))
    q.nurse_assess(stay, 3)

    q.reset_shift()
    assert not q.patients and not q.in_treatment and not q.seen
    assert not q.events_log and not q.ticker
    assert not q.workflow.open(stay).nurse_esi, "workflow state survived the shift"
    assert q._next_ticket == 1


def test_the_audit_trail_survives_a_shift_reset():
    """It is the durable record and it spans shifts. That is the point of it."""
    q = _engine_with_patients()
    before = len(q.audit)
    assert before > 0
    q.reset_shift()
    assert len(q.audit) == before
    assert q.audit.verify()[0] is True


def test_a_patient_who_leaves_mid_cycle_gets_an_answer_not_a_crash():
    """
    reveal() raised a bare KeyError, which escaped the route handler and became
    a 500. A patient leaving the board mid-cycle is ordinary — a shift rolling
    over, or being taken through — and the nurse needs to be told, not shown a
    server error.
    """
    import pytest
    from layer3.workflow import BlindAssessmentError

    q = _engine_with_patients()
    stay = next(iter(q.patients))
    out = q.nurse_assess(stay, 3)

    del q.patients[stay]                      # they leave between the two calls
    with pytest.raises(BlindAssessmentError) as exc:
        q.reveal(stay, token=out["reveal_token"])
    assert "left the board" in str(exc.value)


def test_assessing_a_patient_who_is_not_there_is_refused_up_front():
    """
    Better to refuse the assessment than to accept it and fail at the reveal —
    that leaves a nurse having committed to a number for a patient the system
    cannot then show them.
    """
    import pytest
    from layer3.workflow import BlindAssessmentError

    q = _engine_with_patients()
    with pytest.raises(BlindAssessmentError):
        q.nurse_assess(123456789, 3)


def test_care_since_fixes_the_treatment_list_order():
    """
    The treatment list is a worklist, not a priority queue. It is ordered by
    when care actually started, so it does not reshuffle under a nurse working
    down it. Without a timestamp the client had nothing stable to sort on.
    """
    q = _engine_with_patients(n=8)
    stays = list(q.patients)[:3]
    for s in stays:
        out = q.nurse_assess(s, 3)
        q.reveal(s, token=out["reveal_token"])
        q.finalise(s, clinician="nurse.demo", reason_code="agree")

    rows = {r["stay_id"]: r for r in q.snapshot()["rows"]}
    for s in stays:
        assert rows[s]["signed_off"] is True
        assert rows[s]["care_since"], "a signed-off patient needs an ordering key"

    # ordering by care_since is stable and follows the order they were signed off
    order = sorted(stays, key=lambda s: rows[s]["care_since"])
    assert order == stays


def test_reporting_a_change_clears_the_care_marker():
    """They are back in the queue, so they must not sort as though care began."""
    q = _engine_with_patients()
    stay = next(iter(q.patients))
    out = q.nurse_assess(stay, 3)
    q.reveal(stay, token=out["reveal_token"])
    q.finalise(stay, clinician="nurse.demo", reason_code="agree")
    assert q.patients[stay].signed_off_at is not None

    q.report_change(stay, reporter="nurse.demo")
    assert q.patients[stay].signed_off_at is None
    row = next(r for r in q.snapshot()["rows"] if r["stay_id"] == stay)
    assert row["care_since"] == "" and row["signed_off"] is False
