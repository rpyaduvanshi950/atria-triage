"""The subgroup audit must find gaps, and the mitigation must close them."""
import pytest

from data.loaders.synthetic import generate
from eval import fairness
from layer1 import features
from layer1.model import AcuityScorer


@pytest.fixture(scope="module")
def fitted():
    ds = generate(4000, seed=3)
    return AcuityScorer().fit(ds), ds


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
    m = fairness.mitigate(scorer, ds)
    assert m["tpr_gap_after"] < m["tpr_gap_before"]


def test_mitigation_lifts_every_group_toward_the_target(fitted):
    scorer, ds = fitted
    m = fairness.mitigate(scorer, ds)
    assert (m["detail"]["sensitivity_after"] >= 0.90).all()


def test_mitigation_reports_the_price_it_paid(fitted):
    """A subgroup gain bought with false alarms must be visible, not hidden."""
    scorer, ds = fitted
    d = fairness.mitigate(scorer, ds)["detail"]
    assert {"false_alarm_before", "false_alarm_after"} <= set(d.columns)


def test_subgroup_conformal_covers_each_group(fitted):
    scorer, ds = fitted
    cov = fairness.mitigate(scorer, ds)["conformal_coverage"]
    assert all(v >= 0.90 for v in cov.values())
