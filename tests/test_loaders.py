"""Every loader must return the contract, and Isfahan must refuse to train."""
import pytest

import contracts.schema as schema
import data.loaders as loaders


def test_registry_lists_all_sources():
    assert set(loaders.LOADERS) == {"yale", "mimic_demo", "isfahan", "synthetic"}


def test_synthetic_is_calibrated_to_real_priors():
    ds = loaders.load("synthetic")
    assert "isfahan" in ds.extensions["priors"], "generator fell back to constants"
    assert ds.has_trajectories
    assert (ds.edstays["age"] < 15).sum() > 0, "no paediatric cases generated"


def test_mimic_demo_conforms():
    ds = loaders.load("mimic_demo")
    schema.validate(ds)
    assert ds.has_trajectories
    assert len(ds.edstays) == 222


def test_mimic_demo_has_the_trajectories_layer2_needs():
    ds = loaders.load("mimic_demo")
    counts = ds.vitalsign.groupby("stay_id").size()
    assert (counts >= 3).sum() == 159


def test_isfahan_conforms():
    ds = loaders.load("isfahan")
    schema.validate(ds)
    assert ds.vitalsign is None
    assert not ds.has_trajectories


def test_isfahan_refuses_to_be_trained_on():
    ds = loaders.load("isfahan")
    with pytest.raises(schema.LeakageError, match="workflow"):
        ds.require_trainable()


def test_isfahan_leakage_is_reproducible():
    """Grade 1 has no recorded vitals; grade 3 has them. That is the whole finding."""
    from data.loaders.isfahan import missingness_report
    rep = missingness_report(loaders.load("isfahan"))
    assert rep.loc[1.0, "pct_zero_vitals"] == 100.0
    assert rep.loc[3.0, "pct_zero_vitals"] < 1.0


def test_trainable_sources_pass_the_guard():
    loaders.load("mimic_demo").require_trainable()


def test_yale_gives_extraction_instructions_when_missing():
    try:
        loaders.load("yale")
    except FileNotFoundError as e:
        assert "extract_yale.R" in str(e)
