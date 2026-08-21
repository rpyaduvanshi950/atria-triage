"""The six demo scenarios must behave the way the pitch says they do."""
import pytest

from data.loaders.synthetic import generate
from layer1.model import AcuityScorer
from scenarios import seeds
from scenarios.run import play


@pytest.fixture(scope="module")
def scorer():
    return AcuityScorer().fit(generate(2000, seed=3))


def test_all_six_scenarios_are_defined():
    assert len(seeds.ALL) == 6
    assert [s.number for s in seeds.ALL] == ["01", "02", "03", "04", "05", "06"]


def test_01_quiet_patient_escalates_from_trajectory(scorer):
    q = play(seeds.ALL[0], scorer)
    row = q.snapshot()["rows"][0]
    assert row["band_before"] is not None, "she should not still be at her arrival band"
    assert row["band"] < row["band_before"]


def test_02_paediatric_is_not_judged_by_adult_thresholds(scorer):
    q = play(seeds.ALL[1], scorer)
    row = q.snapshot()["rows"][0]
    # escalated, but not via a false adult hypotension flag at SBP 88
    assert row["band"] <= 2
    assert "Hypotension" not in (row["red_flag"] or "")


def test_03_zero_history_surfaces_what_is_missing(scorer):
    q = play(seeds.ALL[2], scorer)
    row = q.snapshot()["rows"][0]
    assert row["missing"] or row["needs_measurement"]
    assert row["confidence"] in {"MODERATE", "LOW"}


def test_04_surge_stays_inside_the_latency_budget(scorer):
    q = play(seeds.ALL[3], scorer, surge=3.0)
    snap = q.snapshot()
    assert snap["waiting"] >= 40
    assert snap["p95_ms"] < 400


def test_05_override_is_recorded_with_identity_and_reason(scorer):
    q = play(seeds.ALL[4], scorer)
    sid = q.snapshot()["rows"][0]["stay_id"]
    q.override(sid, 4, "reassessed_at_bedside", "nurse.demo")
    entry = q.audit.entries[-1]
    assert entry.kind == "override"
    assert entry.payload["clinician"] == "nurse.demo"
    assert entry.payload["reason_code"] == "reassessed_at_bedside"
    assert entry.payload["downgrade"] is True
    assert q.audit.verify()[0]


def test_06_layer0_still_gates_with_the_model_down(scorer):
    q = play(seeds.ALL[5], scorer, degraded=True)
    row = q.snapshot()["rows"][0]
    assert row["band"] == 1
    assert row["red_flag"], "the red-flag gate must fire without the model"
    assert row["confidence"] == "LOW"


def test_every_scenario_leaves_an_intact_audit_chain(scorer):
    for s in seeds.ALL:
        q = play(s, scorer, degraded=(s.number == "06"))
        assert q.audit.verify()[0], f"scenario {s.number} broke the chain"
