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
    q = QueueEngine(scorer)
    for e in build_events(generate(30, seed=21)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    return q


def test_every_arrival_is_admitted_to_the_queue(played):
    assert len(played.patients) == 30


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
    q = QueueEngine(scorer)
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
    q = QueueEngine(scorer)
    for e in build_events(generate(12, seed=5)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    before = len(q.events_log)
    q.override(next(iter(q.patients)), 3, "reassessed", "nurse.test")
    assert len(q.events_log) == before + 1


def test_degraded_mode_keeps_gating_without_the_model(scorer):
    """Scenario 06: kill the model, Layer 0 carries on."""
    q = QueueEngine(scorer)
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
