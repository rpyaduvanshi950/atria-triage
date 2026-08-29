"""
The statistics behind the honest versions of two headline numbers.

These exist because the previous versions of those numbers were point estimates
with no width, and a point estimate on 36 patients is not a finding. Each test
here is about a specific way the old reporting could mislead.
"""
from __future__ import annotations

import numpy as np
import pytest

from eval.uncertainty import (bootstrap, clopper_pearson, conformal_quantile_index,
                              gap_with_ci, rate_with_ci)


def test_the_interval_never_leaves_the_unit_range():
    """
    The reason for exact intervals rather than the normal approximation. At 96%
    on 79 patients a Wald interval runs past 1.0, and sensitivity cannot exceed
    certainty.
    """
    lo, hi = clopper_pearson(76, 79)
    assert 0.0 <= lo < 0.962 < hi <= 1.0
    assert clopper_pearson(79, 79)[1] == 1.0
    assert clopper_pearson(0, 79)[0] == 0.0


def test_the_interval_narrows_as_the_sample_grows():
    """A 5-point gap on 375 patients and on 300,000 are different findings."""
    widths = [rate_with_ci(np.array([1] * int(n * 0.95) + [0] * int(n * 0.05)))["ci_width"]
              for n in (100, 1_000, 10_000, 100_000)]
    assert widths == sorted(widths, reverse=True)
    assert widths[0] > 10 * widths[-1]


def test_an_unresolvable_gap_reports_itself_as_unresolvable():
    """
    The failure this was written for: two groups whose rates differ on paper but
    cannot be told apart at the sample size available.
    """
    tiny = np.array([1, 1])                       # 2 patients, both flagged
    big = np.array([1] * 9500 + [0] * 500)
    out = gap_with_ci(tiny, big)
    assert out["distinguishable"] is False
    assert out["ci_low"] < 0 < out["ci_high"], "the interval must span zero"


def test_a_real_gap_is_reported_as_real():
    a = np.array([1] * 900 + [0] * 100)           # 90%
    b = np.array([1] * 700 + [0] * 300)           # 70%
    out = gap_with_ci(a, b)
    assert out["distinguishable"] is True
    assert out["ci_low"] > 0
    assert out["gap"] == pytest.approx(0.20, abs=0.01)


def test_a_boundary_rate_does_not_produce_a_zero_width_interval():
    """
    The specific failure that killed the bootstrap version. With two patients
    who were both flagged, every resample is those same two patients — so the
    bootstrap reported zero width and called a difference from a
    300,000-patient group real. Newcombe stays sane at the boundary.
    """
    out = gap_with_ci(np.array([1.0, 1.0]), np.array([1] * 9500 + [0] * 500))
    assert out["ci_high"] - out["ci_low"] > 0.1, "boundary interval collapsed"
    assert out["distinguishable"] is False


def test_the_gap_does_not_allocate_a_billion_floats():
    """
    Regression. The first version resampled indices, so a 300,000-patient
    subgroup meant a 5000 x 300,000 array — 1.5 billion floats, and the process
    was OOM-killed.
    """
    big = np.ones(300_000)
    big[:12_000] = 0
    out = gap_with_ci(big, big, n_boot=5000)
    assert out["gap"] == 0.0
    assert out["distinguishable"] is False


def test_the_conformal_index_is_never_anticonservative():
    """
    Whatever the group size, the threshold it picks must retain at least the
    target fraction of positives. The naive floor() rule can land one order
    statistic the wrong side of that on small groups.
    """
    for n in (5, 20, 37, 79, 100, 375, 1200, 79_000):
        idx = conformal_quantile_index(n, 0.05)
        assert 0 <= idx < n
        assert (n - idx) / n >= 0.95, f"n={n} retains under the target"


def test_the_median_bootstrap_brackets_the_estimate():
    values = np.random.default_rng(0).normal(164, 60, 159)
    out = bootstrap(values)
    assert out["ci_low"] < out["estimate"] < out["ci_high"]
    assert out["n"] == 159


def test_empty_inputs_answer_rather_than_raise():
    """These run inside report generation; a missing subgroup must not crash it."""
    assert bootstrap(np.array([]))["estimate"] is None
    assert gap_with_ci(np.array([]), np.array([1]))["distinguishable"] is None
    assert rate_with_ci(np.array([]))["rate"] is None


# --- the endpoints these numbers describe ------------------------------------

def test_the_critical_diagnosis_endpoint_is_specific():
    """
    The sharper Layer 2 endpoint must not quietly become "was coded at all".
    Altered mental status and unspecified GI haemorrhage are the two most common
    matches for a looser pattern and both span trivial to peri-arrest, so an
    endpoint containing them measures the coding rather than the patient.
    """
    import re
    from eval.lead_time import CRITICAL_DIAGNOSIS

    for title in ("SEPTIC SHOCK", "Cardiac arrest, cause unspecified",
                  "INTRACEREBRAL HEMORRHAGE", "GRAND MAL STATUS",
                  "Non-ST elevation (NSTEMI) myocardial infarction"):
        assert re.search(CRITICAL_DIAGNOSIS, title.upper()), title

    for title in ("ALTERED MENTAL STATUS", "Gastrointestinal hemorrhage, unspecified",
                  "CERVICALGIA", "Chest pain, unspecified"):
        assert not re.search(CRITICAL_DIAGNOSIS, title.upper()), title


def test_a_group_too_small_to_resolve_cannot_set_the_fairness_gap():
    """
    Regression on the audit itself. A subgroup with two positive patients was
    being picked as best-served and setting the reported gap at 6.8%. A rate
    that cannot be pinned down to better than +/- 84 points cannot settle
    whether a 5-point tolerance is met.
    """
    from eval.fairness import EO_TOLERANCE, GAP_NEEDS_CI_NARROWER_THAN

    assert GAP_NEEDS_CI_NARROWER_THAN == EO_TOLERANCE
    assert rate_with_ci(np.array([1.0, 1.0]))["ci_width"] > GAP_NEEDS_CI_NARROWER_THAN
    assert rate_with_ci(np.array([1] * 630 + [0] * 30))["ci_width"] <= GAP_NEEDS_CI_NARROWER_THAN
