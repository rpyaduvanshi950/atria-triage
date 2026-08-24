"""The three atria mortis, and the overlapping-pathology case."""
import pytest

from layer1 import interactions, pathways

WELL = dict(o2sat=98, resprate=15, heartrate=72, sbp=124, gcs=15,
            temperature=98.6, shock_index=0.58, pulse_pressure=46)
ASTHMA = dict(WELL, o2sat=87, resprate=36, heartrate=124, shock_index=0.98)
SHOCK = dict(WELL, sbp=78, heartrate=134, shock_index=1.72, pulse_pressure=18, resprate=22)
HEAD = dict(WELL, gcs=7, sbp=158, heartrate=64, shock_index=0.41, pulse_pressure=62)
COLD_TRAUMA = dict(o2sat=92, resprate=26, heartrate=132, sbp=82, gcs=11,
                   temperature=92.5, shock_index=1.61, pulse_pressure=22)


def test_three_gates_are_defined():
    assert set(pathways.PATHWAYS) == {"respiratory", "circulatory", "neurological"}


def test_every_gate_monitors_four_or_five_parameters():
    for name, spec in pathways.PATHWAYS.items():
        assert 4 <= len(spec["params"]) <= 5, f"{name} has {len(spec['params'])}"


def test_a_well_patient_engages_nothing():
    p = pathways.assess(WELL)
    assert p.severity < 0.3
    assert p.engaged == ()
    assert p.dominant is None


@pytest.mark.parametrize("case,expected", [
    (ASTHMA, "respiratory"), (SHOCK, "circulatory"), (HEAD, "neurological")])
def test_each_clear_presentation_picks_its_own_gate(case, expected):
    assert pathways.assess(case).dominant == expected


def test_specificity_weights_stop_every_gate_lighting_up():
    """Without weights, any sick patient engages all three and the split is useless."""
    p = pathways.assess(HEAD)
    assert p.scores["neurological"] > p.scores["circulatory"]


def test_the_ambiguous_case_scores_highest_ambiguity():
    """Hypothermia plus trauma — the case clinical review raised."""
    clear = pathways.assess(SHOCK).spread
    murky = pathways.assess(COLD_TRAUMA).spread
    assert murky > clear
    assert murky >= 0.75, "should trip the RF12 abstention threshold"


def test_missing_parameters_are_skipped_not_assumed():
    sparse = {"o2sat": 87}
    p = pathways.assess(sparse)
    assert p.observed["respiratory"] == 1
    assert p.observed["circulatory"] == 0


# --- competing pathologies -------------------------------------------------

def test_hypothermia_plus_shock_is_a_treatment_conflict():
    found = interactions.detect(COLD_TRAUMA)
    assert any(i.kind == "conflict" for i in found)
    assert interactions.has_conflict(COLD_TRAUMA)
    assert "necrosis" in " ".join(i.note for i in found)


def test_cushing_reflex_is_detected_as_a_conflict():
    cushing = dict(WELL, sbp=196, heartrate=44, gcs=7)
    assert any("Cushing" in i.note for i in interactions.detect(cushing))


def test_an_uncomplicated_patient_has_no_interactions():
    assert interactions.detect(WELL) == ()
    assert interactions.amplification(WELL) == 1.0


def test_amplification_is_capped():
    """Four interacting problems do not make a patient four times sicker."""
    everything = dict(temperature=92.0, sbp=70, shock_index=2.0, o2sat=80,
                      gcs=6, heartrate=45, resprate=34)
    assert interactions.amplification(everything) <= 1.8


def test_every_interaction_carries_a_citation():
    for i in interactions.INTERACTIONS:
        assert i.citation, f"{i.a}+{i.b} has no citation"
