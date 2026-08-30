"""RF11 and RF12 — when the system refuses to answer."""
from layer0.engine import MIN_FIELDS_TO_TRIAGE, gate
from layer1.model import AcuityScorer
from data.loaders.synthetic import generate, surge_missing_rate
from service.clock import build_events
from service.queue import QueueEngine

AVAILABLE = {"heartrate", "resprate", "o2sat", "sbp", "dbp", "temperature", "age"}
ENOUGH = dict(age=44, sbp=128, o2sat=98, heartrate=76, resprate=15, temperature=98.6)


# --- RF11: too little to go on ---------------------------------------------

def test_a_chief_complaint_alone_cannot_be_triaged():
    """You cannot triage a sentence."""
    result = gate({"age": 44}, AVAILABLE)
    assert result.hard_stop
    assert result.abstains
    assert "RF11" in result.explain()


def test_below_the_floor_is_a_hard_stop():
    assert gate({"age": 44, "sbp": 128}, AVAILABLE).hard_stop
    assert not gate(ENOUGH, AVAILABLE).hard_stop


def test_the_floor_is_stated_not_hidden():
    assert MIN_FIELDS_TO_TRIAGE == 3
    assert str(MIN_FIELDS_TO_TRIAGE) in gate({"age": 44}, AVAILABLE).explain()


def test_an_abstention_is_not_a_low_acuity_finding():
    """We do not know what this patient is, so they go ahead of the cleared."""
    assert gate({"age": 44}, AVAILABLE).priority == 2


def test_a_confirmed_red_flag_survives_sparse_data():
    """A recorded SpO2 of 82 does not become uncertain because the form is blank."""
    result = gate({"age": 44, "o2sat": 82}, AVAILABLE)
    assert result.is_red
    assert not result.hard_stop
    assert result.priority == 1


# --- RF12: cannot classify --------------------------------------------------

def test_ambiguity_triggers_abstention():
    result = gate({**ENOUGH, "_pathway_ambiguity": 0.9, "_pathway_severity": 0.9}, AVAILABLE)
    assert result.ambiguous
    assert "RF12" in result.explain()


def test_ambiguity_without_severity_is_not_an_emergency():
    """Two mildly engaged gates on a well patient is not a crisis."""
    result = gate({**ENOUGH, "_pathway_ambiguity": 0.9, "_pathway_severity": 0.1}, AVAILABLE)
    assert not result.ambiguous


def test_clear_presentations_do_not_abstain():
    result = gate({**ENOUGH, "_pathway_ambiguity": 0.3, "_pathway_severity": 0.9}, AVAILABLE)
    assert not result.ambiguous


# --- the two confidences are separate ---------------------------------------

def test_a_patient_can_be_certainly_critical_and_diagnostically_opaque():
    """The whole point of splitting the two numbers."""
    m = AcuityScorer().fit(generate(1500, seed=3))
    cold_trauma = dict(heartrate=132, sbp=82, dbp=60, o2sat=92, resprate=26,
                       temperature=92.5, age=41, gcs=11, pain=6,
                       is_geriatric=0.0, is_paediatric=0.0,
                       shock_index=1.61, pulse_pressure=22,
                       n_vitals_missing=0, arrived_by_ambulance=1)
    s = m.score_one(cold_trauma)
    assert s.band <= 2, "should be recognised as critical"
    assert s.diagnostic_confidence == "LOW", "should admit it cannot say what is wrong"
    assert s.conflicts, "should surface the vasopressor conflict"


def test_a_well_patient_is_diagnostically_easy():
    m = AcuityScorer().fit(generate(1500, seed=3))
    well = dict(heartrate=74, sbp=122, dbp=78, o2sat=98, resprate=15,
                temperature=98.4, age=34, gcs=15, pain=1,
                is_geriatric=0.0, is_paediatric=0.0, shock_index=0.61,
                pulse_pressure=44, n_vitals_missing=0, arrived_by_ambulance=0)
    assert m.score_one(well).diagnostic_confidence == "HIGH"


# --- surge degrades data, which drives abstention ---------------------------

def test_surge_reduces_data_quality():
    assert surge_missing_rate(0.18, 3.0) > surge_missing_rate(0.18, 1.0)
    assert surge_missing_rate(0.18, 50.0) <= 0.55, "must stay bounded"


def test_more_missing_data_means_more_abstentions():
    """The failure mode clinical review predicted, made visible."""
    scorer = AcuityScorer().fit(generate(1500, seed=3))

    def run(missing_rate):
        # Arrivals only. Every later observation now re-runs Layers 0 and 1, so
        # an abstention is resolved the moment enough vitals arrive — which is
        # the behaviour that makes a manual check-in work. Counting after a full
        # replay measured how much data eventually turned up, not how the gate
        # responds to having little of it.
        q = QueueEngine(scorer, slots=0)
        for e in build_events(generate(30, seed=7, hours=2.0, missing_rate=missing_rate)):
            if e.kind == "arrival":
                q.on_arrival(e)
        return q.snapshot()["abstained"]

    assert run(0.50) > run(0.10)


def test_an_abstention_is_written_to_the_audit_log():
    scorer = AcuityScorer().fit(generate(1200, seed=3))
    q = QueueEngine(scorer, slots=0)
    for e in build_events(generate(30, seed=7, hours=2.0, missing_rate=0.6)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    assert any(entry.kind == "abstain" for entry in q.audit)
    assert q.audit.verify()[0]


# --- parallel lanes ---------------------------------------------------------

def test_band_one_gets_its_own_lane():
    from service.queue import lane_for
    assert lane_for(1) == "RESUS"
    assert lane_for(2) == "ACUTE" and lane_for(3) == "ACUTE"
    assert lane_for(4) == "FAST TRACK" and lane_for(5) == "FAST TRACK"


def test_the_board_reports_lane_depth():
    scorer = AcuityScorer().fit(generate(1200, seed=3))
    q = QueueEngine(scorer, slots=3)
    for e in build_events(generate(30, seed=21, hours=3.0)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    lanes = q.snapshot()["lanes"]
    assert set(lanes) == {"RESUS", "ACUTE", "FAST TRACK"}
