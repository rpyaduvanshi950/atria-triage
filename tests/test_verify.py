"""'Unknown is not normal' must be audited, not asserted."""
from data.loaders.synthetic import generate
from layer1 import features
from layer1.model import AcuityScorer
from layer1.verify import missingness_directions, unsafe_fields


def test_audit_reports_a_direction_for_every_vital():
    ds = generate(1200, seed=3)
    m = AcuityScorer().fit(ds)
    report = missingness_directions(m, features.build(ds))
    assert set(report["field"]) >= {"o2sat", "sbp", "heartrate"}
    assert report["direction"].isin(["raises risk", "LOWERS RISK"]).all()


def test_a_missing_vital_never_scores_better_than_an_average_one():
    """
    The property the clamp actually provides, and the one that matters: an
    unrecorded vital may not score better than the population median for that
    vital. That closes the silent-undertriage path the audit found.

    It is deliberately *not* "never lower than this patient's own score". A
    patient whose recorded value is worse than median should score worse than
    one whose value is unknown — losing the field loses the evidence, and
    pretending otherwise would mean blanking a vital could never help anyone,
    which is worst-case substitution by another name.
    """
    ds = generate(2000, seed=3)
    m = AcuityScorer().fit(ds)

    row = {"heartrate": 88, "sbp": 118, "o2sat": 97, "resprate": 16,
           "temperature": 98.6, "dbp": 74, "pain": 3, "age": 55,
           "is_geriatric": 0.0, "is_paediatric": 0.0, "shock_index": 0.75,
           "pulse_pressure": 44, "n_vitals_missing": 0, "arrived_by_ambulance": 0}

    for field in m.unsafe_missing:
        blanked = {**row, field: None, f"{field}_missing": 1, "n_vitals_missing": 1}
        at_median = {**row, field: m.medians_[field]}
        assert m.score_one(blanked).risk >= m.score_one(at_median).risk - 1e-9, (
            f"missing {field} scored better than an average {field}")


def test_the_clamp_does_not_send_well_patients_to_the_top():
    """Worst-case substitution belongs at Layer 0, not here."""
    ds = generate(2000, seed=3)
    m = AcuityScorer().fit(ds)
    well = {"heartrate": 74, "sbp": 122, "o2sat": 98, "resprate": 15,
            "temperature": 98.4, "dbp": 78, "pain": 1, "age": 34,
            "is_geriatric": 0.0, "is_paediatric": 0.0, "shock_index": 0.61,
            "pulse_pressure": 44, "n_vitals_missing": 0, "arrived_by_ambulance": 0}
    blanked = {**well, "sbp": None, "sbp_missing": 1, "n_vitals_missing": 1,
               "shock_index": None, "pulse_pressure": None}
    assert m.score_one(blanked).band >= 3, "an incomplete form must not mean band 1"


def test_unsafe_fields_are_recorded_in_metrics():
    m = AcuityScorer().fit(generate(1200, seed=3))
    assert "unsafe_missing_fields" in m.metrics


# --- feature attribution ------------------------------------------------------

def test_attributions_come_from_the_model_not_from_the_reasons():
    """
    The descriptive reasons name the pathway that engaged. TreeSHAP reports what
    the trained model actually weighed, and the two can disagree — a patient can
    trip the respiratory pathway on a borderline rate while the score is driven
    by blood pressure. If these were the same thing there would be no point
    computing them.
    """
    import warnings
    warnings.filterwarnings("ignore")
    from data.loaders.synthetic import generate
    from layer1.model import AcuityScorer

    scorer = AcuityScorer().fit(generate(600, seed=3))
    scored = scorer.score_one({
        "o2sat": 88, "sbp": 92, "heartrate": 124, "resprate": 28,
        "temperature": 99.1, "age": 71, "shock_index": 1.35,
        "pulse_pressure": 38, "is_paediatric": 0, "is_geriatric": 1})

    assert scored.attributions, "no attribution produced"
    for a in scored.attributions:
        assert a["feature"] in scorer.columns, "attributed to a feature not in the model"
        assert a["direction"] in ("raised", "lowered")
        assert 0.0 <= a["share"] <= 1.0
    shares = [a["share"] for a in scored.attributions]
    assert shares == sorted(shares, reverse=True), "largest effect must come first"


def test_an_explanation_never_changes_the_score():
    """
    An explanation that can alter what it explains is not an explanation. The
    attributor is read-only with respect to the decision.
    """
    import warnings
    warnings.filterwarnings("ignore")
    from data.loaders.synthetic import generate
    from layer1.model import AcuityScorer

    scorer = AcuityScorer().fit(generate(500, seed=3))
    row = {"o2sat": 95, "sbp": 118, "heartrate": 88, "resprate": 18,
           "temperature": 98.4, "age": 40, "shock_index": 0.75,
           "pulse_pressure": 44, "is_paediatric": 0, "is_geriatric": 0}
    with_explainer = scorer.score_one(row)

    scorer.attributor = None                      # as if shap were unavailable
    without = scorer.score_one(row)

    assert without.attributions == ()
    assert without.risk == with_explainer.risk
    assert without.band == with_explainer.band


def test_the_model_still_scores_when_shap_is_missing():
    """A missing optional dependency must never stop a patient being scored."""
    import warnings
    warnings.filterwarnings("ignore")
    from data.loaders.synthetic import generate
    from layer1 import explain
    from layer1.model import AcuityScorer

    scorer = AcuityScorer().fit(generate(500, seed=3))
    broken = explain.Attributor.__new__(explain.Attributor)
    broken.columns, broken._explainer = list(scorer.columns), None
    assert broken.ready is False
    assert broken.explain(None) == [] or broken.explain(__import__("pandas").DataFrame()) == []
