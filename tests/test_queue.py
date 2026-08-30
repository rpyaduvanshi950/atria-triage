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


def _triage_everyone(q) -> None:
    """
    Stand in for the nurses. A bay only takes a patient who has been signed
    off, so a test about throughput has to triage before it can measure it.
    """
    for stay_id in list(q.patients):
        if q.patients[stay_id].signed_off:
            continue
        try:
            out = q.nurse_assess(stay_id, q.patients[stay_id].band)
            q.reveal(stay_id, token=out["reveal_token"])
            q.finalise(stay_id, clinician="nurse.test",
                       reason_code="reassessed_at_bedside")
        except Exception:
            continue


def test_patients_are_seen_and_leave_when_there_is_capacity(scorer):
    """With treatment slots, the queue drains instead of growing without bound."""
    q = QueueEngine(scorer, slots=3)
    for e in build_events(generate(40, seed=21, hours=3.0)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
        _triage_everyone(q)
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
        _triage_everyone(q)
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


def test_missing_vitals_are_surfaced_not_hidden(scorer):
    """
    Checked on a patient who is genuinely missing a reading, rather than over a
    replayed shift.

    Every observation now re-runs Layers 0 and 1 over the readings as they
    stand, so missingness is resolved as vitals arrive — which is the point of
    that change. Asserting over a finished replay therefore tested whether
    anyone was still un-measured at the end, which is a fact about the
    generator, not about whether the board surfaces a gap.
    """
    from service.clock import Event
    import pandas as pd

    q = QueueEngine(scorer, slots=0)
    q.on_arrival(Event(at=pd.Timestamp("2026-01-01 09:00"), kind="arrival",
                       stay_id=1, payload={"age": 44, "chiefcomplaint": "cough",
                                           "o2sat": 97, "heartrate": 82,
                                           "resprate": 16}))
    row = q.snapshot()["rows"][0]
    assert row["missing"] or row["needs_measurement"], \
        "a patient with no blood pressure must say so"
    assert "sbp" in " ".join(row["missing"]) or row["needs_measurement"]


def test_a_patient_needing_attention_is_ranked_there_by_their_band(played):
    """
    Replaces an assertion that AWAITING sorted above everything regardless of
    band, which is what made the board disagree with the ratings printed on it.

    The guarantee is the same and stronger: Layer 0 gives anyone who needs
    attention first a band that puts them there — a red flag is band 1, an
    abstention band 2 — so the ordering follows the rating and the rating
    already carries the urgency. Sorting on the state as well applied it twice.
    """
    rows = [r for r in played.snapshot()["rows"] if r["state"] != "IN TREATMENT"]
    if not rows:
        return

    bands = [r["band"] for r in rows]
    assert bands == sorted(bands), "the board must follow its own ratings"

    for r in rows:
        if r["red_flag"]:
            assert r["band"] == 1, "a fired rule must be band 1"
        elif r["abstained"]:
            assert r["band"] <= 2, "an unknown patient goes ahead of the cleared"


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


def test_a_patient_who_deteriorates_after_sign_off_is_not_stranded():
    """
    A patient could get permanently stuck on the board, and it took a stalled
    demo to notice.

    A Layer 2 escalation cleared the patient's signed_off flag, correctly, but
    left the workflow at SIGNED. The two then disagreed: nothing could assess
    them, because the workflow refuses a second cycle without reopen(); and
    nothing could treat them, because a bay only takes the signed-off. They sat
    there for the rest of the shift, escalating and unreachable.
    """
    from layer3.workflow import Stage

    q = _engine_with_patients(n=10)
    stay = next(iter(q.patients))
    out = q.nurse_assess(stay, 3)
    q.reveal(stay, token=out["reveal_token"])
    q.finalise(stay, clinician="nurse.demo", reason_code="agree")
    assert q.workflow.open(stay).stage is Stage.SIGNED

    # deterioration, arriving as a trajectory escalation rather than by hand
    p = q.patients[stay]
    p.signed_off = True
    q.workflow.open(stay).stage = Stage.SIGNED
    p.band = 3
    for _ in range(4):
        p.history.append({"charttime": q.now, "o2sat": 85, "sbp": 84,
                          "heartrate": 132, "resprate": 30, "temperature": 37.0})
    q.on_vitals(type("E", (), {"stay_id": stay, "at": q.now,
                               "payload": {"o2sat": 85, "sbp": 84, "heartrate": 132,
                                           "resprate": 30, "temperature": 37.0},
                               "kind": "vitals"})())

    if not p.signed_off:          # the escalation fired
        assert q.workflow.open(stay).stage is not Stage.SIGNED, \
            "workflow still signed while the patient is not: they are stranded"
        # and they can be assessed again, which is the whole point
        assert q.nurse_assess(stay, 1)["reveal_token"]


def test_a_bay_only_takes_a_patient_who_has_been_triaged():
    """
    Without this, a free bay pulled whoever was most urgent straight out of the
    arrivals list. On an empty department the first patients went to treatment
    having never been assessed, so the board opened with an empty attention
    queue and a full treatment bay, which is exactly backwards for a triage
    product.
    """
    q = _engine_with_patients(n=10)
    q.slots = 5
    q._advance_service()
    assert not q.in_treatment, "an untriaged patient was taken through"

    stay = next(iter(q.patients))
    out = q.nurse_assess(stay, 3)
    q.reveal(stay, token=out["reveal_token"])
    q.finalise(stay, clinician="nurse.demo", reason_code="agree")
    q._advance_service()
    assert stay in q.in_treatment, "a signed-off patient was not taken through"


def test_the_ranking_explanation_describes_the_sort_that_actually_runs():
    """
    The explanation is written against snapshot()'s sort, not against
    layer2/ranking.py, which the engine does not currently use. An explanation
    of a ranking that is not the one being performed is worse than none: it
    reads as authoritative and is wrong.
    """
    q = _engine_with_patients(n=12)
    rows = q.snapshot()["rows"]
    assert all(r["rank_because"] for r in rows), "every patient needs a reason"

    for r in rows:
        joined = " ".join(r["rank_because"])
        assert f"Priority {r['band']}" in joined, "the band must be named"
        assert "breaks ties" in joined, "the tiebreak must be named"

    # a patient in a bay is explained as being below everyone still waiting
    q.slots = 3
    stay = next(iter(q.patients))
    out = q.nurse_assess(stay, 3)
    q.reveal(stay, token=out["reveal_token"])
    q.finalise(stay, clinician="nurse.test", reason_code="agree")
    q._advance_service()
    row = next(r for r in q.snapshot()["rows"] if r["stay_id"] == stay)
    assert "treatment bay" in " ".join(row["rank_because"]).lower()


def test_a_red_flag_is_named_as_the_reason_it_is_first():
    """The loudest thing about a patient should be the first thing explained."""
    q = _engine_with_patients(n=12)
    flagged = [p for p in q.patients.values() if p.red_flag]
    if not flagged:
        import pytest
        pytest.skip("no red flag in this fixture")
    why = flagged[0].rank_because(q.now)
    assert any(p.red_flag in w for p in flagged[:1] for w in why)


def test_the_board_is_ordered_by_the_rating_it_prints():
    """
    The sort used to lift every AWAITING patient above the rating, so a band 4
    could sit above a band 2 and the list stopped agreeing with the numbers on
    it. Anything that genuinely needs attention first already gets a band from
    Layer 0 for it — a red flag is band 1, an abstention band 2 — so sorting on
    the state as well applied that twice.
    """
    q = _engine_with_patients(n=16)
    bands = [r["band"] for r in q.snapshot()["rows"]
             if r["state"] != "IN TREATMENT"]
    assert bands == sorted(bands), f"board disagrees with its own ratings: {bands}"


def test_the_model_is_held_but_the_safety_rules_are_not():
    """
    A rating that moves on every reading is unreadable, so Layer 1 is throttled.
    Layer 0 is deliberately outside that: a red flag is a measured threshold and
    must fire on the reading that crosses it, not on the next one that happens
    to fall after a timer.
    """
    import pandas as pd
    from service.clock import Event
    from service.queue import RESCORE_INTERVAL

    q = _engine_with_patients(n=4)
    t = pd.Timestamp("2026-01-01 09:00")
    q.on_arrival(Event(at=t, kind="arrival", stay_id=77, payload={
        "age": 60, "chiefcomplaint": "chest pain", "o2sat": 97, "sbp": 130,
        "heartrate": 80, "resprate": 16, "temperature": 98.4}))
    p = q.patients[77]
    scored_at = p.last_scored

    def reading(offset_s, **vitals):
        at = t + pd.Timedelta(seconds=offset_s)
        q.on_vitals(Event(at=at, kind="vitals", stay_id=77,
                          payload={"stay_id": 77, "charttime": at, **vitals}))

    reading(2, o2sat=96, sbp=128, heartrate=84, resprate=17, temperature=98.4)
    assert p.last_scored == scored_at, "the model ran again inside the hold"

    reading(int(RESCORE_INTERVAL.total_seconds()) + 2,
            o2sat=95, sbp=126, heartrate=86, resprate=18, temperature=98.4)
    assert p.last_scored != scored_at, "the model never ran again"

    # and a red flag arriving inside a fresh hold window still fires at once
    held_at = p.last_scored
    reading(int(RESCORE_INTERVAL.total_seconds()) + 4,
            o2sat=84, sbp=126, heartrate=86, resprate=18, temperature=98.4)
    assert p.last_scored == held_at, "precondition: still inside the hold"
    assert p.red_flag and "RF02" in p.red_flag, "a red flag was delayed by the hold"
