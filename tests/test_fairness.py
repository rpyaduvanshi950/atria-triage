"""The subgroup audit must find gaps, and the mitigation must close them."""
import pytest

from data.loaders.synthetic import generate
from eval import fairness
from layer1 import features
from layer1.model import AcuityScorer


@pytest.fixture(scope="module")
def fitted():
    # Large enough that the mitigation has a held-out half to measure on and
    # each age band still has enough positives to estimate a rate. The previous
    # 4,000 left every subgroup's interval wider than the tolerance, at which
    # point the honest answer is "cannot resolve" and there is no gap to test.
    ds = generate(12000, seed=3)
    return AcuityScorer().fit(ds), ds


#: Synthetic subgroups here have 130-300 positive patients, which pins a ~95%
#: rate to about eight points. The published Yale figures use the real 5-point
#: tolerance against subgroups with thousands of positives; this loosening
#: exercises the same code path at a scale a test can afford.
TEST_TOLERANCE = 0.12


def test_audit_covers_every_available_attribute(fitted):
    scorer, ds = fitted
    report = fairness.audit(scorer, ds)
    assert set(report["attribute"]) >= {"age_band", "sex"}
    assert (report["n"] >= 30).all()


def test_audit_reports_undertriage_per_group(fitted):
    scorer, ds = fitted
    report = fairness.audit(scorer, ds)
    assert report["undertriage"].between(0, 1).all()
    assert (report["sensitivity"] + report["undertriage"]).round(6).eq(1.0).all()


def test_equalised_odds_flags_a_gap_outside_tolerance(fitted):
    scorer, ds = fitted
    eo = fairness.equalised_odds(fairness.audit(scorer, ds))
    assert "equalised_odds_diff" in eo.columns
    assert eo["within_tolerance"].dtype == bool
    assert (eo["equalised_odds_diff"] >= 0).all()


def test_mitigation_narrows_the_sensitivity_gap(fitted):
    """The claim on the fairness slide, as a test."""
    scorer, ds = fitted
    m = fairness.mitigate(scorer, ds, resolve_tolerance=TEST_TOLERANCE)
    assert m["tpr_gap_after"] is not None, "no subgroup was resolvable"
    assert m["tpr_gap_after"] < m["tpr_gap_before"]


def test_the_gap_is_measured_on_patients_it_was_not_fitted_to(fitted):
    """
    The flaw that made the old 5.0% meaningless. Thresholds chosen on the same
    patients they are then scored against reproduce their own quantile, so the
    reported sensitivity was a restatement of the fit rather than a result.
    """
    scorer, ds = fitted
    m = fairness.mitigate(scorer, ds, resolve_tolerance=TEST_TOLERANCE)
    assert m["n_calibrate"] > 0 and m["n_test"] > 0
    assert abs(m["n_calibrate"] - m["n_test"]) < 0.1 * (m["n_calibrate"] + m["n_test"])


def test_a_group_whose_interval_exceeds_the_tolerance_is_named_not_dropped(fitted):
    """
    Excluding a subgroup from the gap is defensible; excluding it silently is
    not. Whatever cannot be resolved has to appear in the output.
    """
    scorer, ds = fitted
    m = fairness.mitigate(scorer, ds, resolve_tolerance=TEST_TOLERANCE)
    assert "groups_too_small_to_resolve" in m
    reported = set(m["detail"]["group"])
    assert set(m["groups_too_small_to_resolve"]) <= reported


def test_mitigation_lifts_every_resolvable_group_toward_the_target(fitted):
    scorer, ds = fitted
    m = fairness.mitigate(scorer, ds, resolve_tolerance=TEST_TOLERANCE)
    # Only groups whose rate can actually be estimated. A group of two patients
    # sits wherever those two patients happened to land.
    resolvable = m["detail"][m["detail"]["ci_width"] <= TEST_TOLERANCE]
    assert len(resolvable) > 0
    assert (resolvable["sensitivity_after"] >= 0.90).all()


def test_mitigation_reports_the_price_it_paid(fitted):
    """A subgroup gain bought with false alarms must be visible, not hidden."""
    scorer, ds = fitted
    d = fairness.mitigate(scorer, ds, resolve_tolerance=TEST_TOLERANCE)["detail"]
    assert {"false_alarm_before", "false_alarm_after"} <= set(d.columns)


def test_subgroup_conformal_covers_each_group(fitted):
    scorer, ds = fitted
    cov = fairness.mitigate(scorer, ds, resolve_tolerance=TEST_TOLERANCE)["conformal_coverage"]
    assert all(v >= 0.90 for v in cov.values())
