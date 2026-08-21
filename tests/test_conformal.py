"""Mondrian conformal: the guarantee must land on the critical class."""
import numpy as np
import pytest

from data.loaders.synthetic import generate
from layer1.conformal import MondrianConformal, PredictionSet
from layer1.model import AcuityScorer


@pytest.fixture(scope="module")
def imbalanced():
    """Rare positives that are also *harder* — where marginal conformal fails."""
    rng = np.random.default_rng(0)
    n = 6000
    y = (rng.random(n) < 0.06).astype(int)
    p = np.where(y == 1, rng.beta(2.2, 3.0, n), rng.beta(1.6, 9.0, n))
    return p, y


def test_class_conditional_coverage_holds_for_the_rare_class(imbalanced):
    p, y = imbalanced
    mc = MondrianConformal(alpha=0.05).fit(p, y)
    assert mc.coverage["class_1"] >= 0.90, "critical class under-covered"
    assert mc.coverage["class_0"] >= 0.90


def test_mondrian_covers_the_rare_class_better_than_marginal(imbalanced):
    """The reason we use Mondrian at all, stated as a test."""
    p, y = imbalanced
    mc = MondrianConformal(alpha=0.05).fit(p, y)

    scores = 1 - np.where(y == 1, p, 1 - p)
    q = np.quantile(scores, 0.95)
    marginal_rare = float(np.mean((1 - p[y == 1]) <= q))

    assert mc.coverage["class_1"] >= marginal_rare


def test_subgroup_conditional_guarantee(imbalanced):
    """The taxonomy is arbitrary — class x subgroup gives per-subgroup coverage."""
    p, y = imbalanced
    rng = np.random.default_rng(1)
    groups = rng.choice(["a", "b"], len(y))
    mc = MondrianConformal(alpha=0.05).fit(p, y, groups)
    assert ("a", 1) in mc.quantiles and ("b", 1) in mc.quantiles


def test_an_empty_set_is_never_reported_as_confident():
    """Out of distribution must escalate, never reassure."""
    empty = PredictionSet(frozenset(), 0.05)
    assert empty.is_empty
    assert empty.confidence == "LOW"


def test_an_ambiguous_set_is_reported_as_uncertain():
    assert PredictionSet(frozenset({0, 1}), 0.05).confidence == "MODERATE"


def test_scorer_never_returns_a_risk_without_a_prediction_set():
    m = AcuityScorer().fit(generate(1200, seed=3))
    s = m.score_one({"heartrate": 96, "sbp": 108, "o2sat": 95, "resprate": 20,
                     "temperature": 99.0, "dbp": 66, "pain": 5, "age": 62,
                     "is_geriatric": 1.0, "is_paediatric": 0.0,
                     "shock_index": 0.89, "pulse_pressure": 42, "n_vitals_missing": 0})
    assert s.prediction_set is not None
    assert s.as_dict()["prediction_set"]["coverage"] == 0.95


def test_calibration_uses_data_held_out_from_fitting():
    """Calibrating on training data would void the guarantee."""
    m = AcuityScorer().fit(generate(1200, seed=3))
    assert m.metrics["n_cal"] > 0
    assert m.metrics["n_cal"] + m.metrics["n_train"] + m.metrics["n_test"] <= 1200
