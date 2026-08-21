"""One test per red-flag rule, plus the properties that make Layer 0 trustworthy."""
import pytest

from layer0.engine import RuleTable, gate

WELL = {"gcs": 15, "o2sat": 98, "sbp": 120, "heartrate": 75,
        "resprate": 16, "temperature": 98.6, "age": 40}


def fired_ids(patient):
    return {r.id for r in gate(patient).fired}


def test_well_patient_fires_nothing():
    assert not gate(WELL).is_red


def test_all_ten_rules_present():
    assert len(RuleTable().rules) == 10


def test_every_rule_has_a_citation():
    for rule in RuleTable().rules:
        assert rule.get("citation"), f"{rule['id']} has no citation"


# --- one test per rule -----------------------------------------------------

def test_rf01_gcs():
    assert "RF01" in fired_ids({**WELL, "gcs": 8})
    assert "RF01" not in fired_ids({**WELL, "gcs": 9})

def test_rf02_hypoxaemia():
    assert "RF02" in fired_ids({**WELL, "o2sat": 89})
    assert "RF02" not in fired_ids({**WELL, "o2sat": 90})

def test_rf03_hypotension():
    assert "RF03" in fired_ids({**WELL, "sbp": 89})
    assert "RF03" not in fired_ids({**WELL, "sbp": 90})

def test_rf04_seizure():
    assert "RF04" in fired_ids({**WELL, "active_seizure": True})

def test_rf05_airway():
    assert "RF05" in fired_ids({**WELL, "airway_compromise": True})

def test_rf06_haemorrhage():
    assert "RF06" in fired_ids({**WELL, "uncontrolled_haemorrhage": True})

def test_rf07_anaphylaxis():
    assert "RF07" in fired_ids({**WELL, "anaphylaxis": True})

def test_rf08_stroke_only_inside_window():
    inside = {**WELL, "stroke_signs": True, "symptom_onset_minutes": 200}
    outside = {**WELL, "stroke_signs": True, "symptom_onset_minutes": 400}
    assert "RF08" in fired_ids(inside)
    assert "RF08" not in fired_ids(outside)

def test_rf09_eclampsia():
    assert "RF09" in fired_ids({**WELL, "eclampsia": True})

def test_rf10_paediatric_retractions_is_age_gated():
    assert "RF10" in fired_ids({**WELL, "age": 3, "retractions": True})
    assert "RF10" not in fired_ids({**WELL, "age": 40, "retractions": True})


# --- the design commitments ------------------------------------------------

def test_unknown_is_not_normal_for_numeric_vitals():
    """A missing SpO2 is never read as a reassuring one."""
    blank = {k: v for k, v in WELL.items() if k != "o2sat"}
    result = gate(blank)
    assert "RF02" in {r.id for r in result.unresolved}
    assert "o2sat" in result.imputed_fields
    assert result.priority < 5, "a missing vital must still raise urgency"


def test_unknown_is_not_treated_as_critical_either():
    """
    Blanket worst-case escalation floods the queue and trains staff to ignore
    the board — the exact failure this system exists to prevent.
    """
    blank = {k: v for k, v in WELL.items() if k != "o2sat"}
    result = gate(blank)
    assert not result.is_red, "an unmeasured vital is not a confirmed emergency"
    assert result.needs_measurement
    assert result.priority == 2
    assert "measure" in result.explain()


def test_confirmed_flag_outranks_an_unresolved_one():
    confirmed = gate({**WELL, "o2sat": 85})
    unresolved = gate({k: v for k, v in WELL.items() if k != "o2sat"})
    assert confirmed.priority < unresolved.priority


def test_imputation_is_disclosed_not_silent():
    blank = {k: v for k, v in WELL.items() if k != "sbp"}
    rule = next(r for r in gate(blank).unresolved if r.id == "RF03")
    assert "sbp" in rule.imputed
    assert "assumed-worst" in rule.reason()


def test_witnessed_events_are_not_imputed_true():
    """Absence of an observation is not evidence of the event."""
    assert "RF04" not in fired_ids(WELL)
    assert "RF05" not in fired_ids(WELL)


def test_a_fired_flag_forces_the_most_urgent_band():
    assert gate({**WELL, "gcs": 5}).priority == 1


def test_layer0_needs_no_model_and_no_network(monkeypatch):
    """Degraded mode: the gate is pure and importable with nothing else alive."""
    import socket

    def deny(*a, **k):
        raise AssertionError("Layer 0 attempted network access")

    monkeypatch.setattr(socket, "socket", deny)
    assert gate({**WELL, "o2sat": 80}).is_red


def test_uncollected_fields_are_not_treated_as_missing_measurements():
    """
    No source in this project carries GCS. Gating every patient on an assumed
    GCS of 3 would fire RF01 on all of them and make the gate meaningless.
    """
    available = {"heartrate", "resprate", "o2sat", "sbp", "dbp", "temperature", "age"}
    result = gate({"o2sat": 98, "sbp": 120, "age": 40}, available)
    assert "RF01" in result.not_evaluable
    assert "RF01" not in {r.id for r in result.fired + result.unresolved}


def test_a_measured_field_still_gates_when_absent_for_this_patient():
    """Uncollected is skipped; unrecorded-for-this-patient is not."""
    available = {"heartrate", "resprate", "o2sat", "sbp", "dbp", "temperature", "age"}
    result = gate({"sbp": 120, "age": 40}, available)   # o2sat absent
    assert "RF02" in {r.id for r in result.unresolved}
    assert result.needs_measurement
