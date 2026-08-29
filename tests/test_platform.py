"""
The four pieces that turn a demo into something deployable: durable storage,
authentication, a frozen model, and shadow mode.

These test the properties that make each one worth having — that the chain
survives a restart, that a role cannot exceed itself, that a tampered artifact
is refused, and that shadow mode genuinely does not move anybody — rather than
that the code runs.
"""
from __future__ import annotations

import json
import os
import pickle
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from data.loaders.synthetic import generate
from layer1.model import AcuityScorer
from layer3.audit import AuditLog
from layer3.store import AuditStore
from service import auth, shadow as shadow_mode
from service.clock import build_events
from service.queue import QueueEngine


# --- persistence -------------------------------------------------------------

@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "audit.db")


def test_chain_survives_a_restart(db_path):
    """A hash chain that dies with the process proves nothing."""
    log = AuditLog(store=AuditStore(db_path))
    log.append("arrival", 1, "09:00", band=3)
    log.append("sign_off", 1, "09:05", final_esi=3)
    first_hash = log.entries[-1].hash

    reopened = AuditLog(store=AuditStore(db_path))
    assert len(reopened) == 2
    assert reopened.entries[-1].hash == first_hash
    assert reopened.verify()[0] is True

    # and the chain continues from where it left off rather than restarting
    reopened.append("override", 1, "09:09", frm=3, to=4)
    assert reopened.entries[-1].prev_hash == first_hash
    assert reopened.verify()[0] is True


def test_the_database_refuses_edits_and_deletes(db_path):
    """Append-only is enforced by the store, not by everyone remembering."""
    import sqlite3
    log = AuditLog(store=AuditStore(db_path))
    log.append("sign_off", 7, "09:00", final_esi=2)

    con = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE audit SET kind = 'nothing_happened' WHERE seq = 0")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("DELETE FROM audit WHERE seq = 0")


def test_a_tampered_row_breaks_verification(db_path):
    """
    Belt and braces: if someone gets past the triggers — a direct file edit, a
    copy of the database with the triggers dropped — the chain still says so.
    """
    store = AuditStore(db_path)
    log = AuditLog(store=store)
    log.append("sign_off", 1, "09:00", final_esi=4)
    log.append("sign_off", 2, "09:01", final_esi=2)

    store._db.execute("DROP TRIGGER audit_no_update")
    store._db.execute("UPDATE audit SET payload = ? WHERE seq = 0",
                      (json.dumps({"final_esi": 1}),))
    store._db.commit()

    reopened = AuditLog(store=AuditStore(db_path))
    intact, note = reopened.verify()
    assert intact is False and "modified" in note


def test_in_memory_is_still_the_default():
    """No store, no file. Tests and scenarios must not leave a database behind."""
    log = AuditLog()
    log.append("arrival", 1, "09:00")
    assert log.store is None and log.verify()[0] is True


# --- authentication ----------------------------------------------------------

@pytest.fixture()
def api():
    """A TestClient over a fresh engine, with the background replay stubbed."""
    import service.app as app_module

    async def _no_replay(*_a, **_kw):
        return None

    original_replay, original_engine = app_module._replay, app_module.engine
    app_module._replay = _no_replay
    app_module.engine = QueueEngine(AcuityScorer().fit(generate(400, seed=3)), slots=0)
    for e in build_events(generate(8, seed=5)):
        (app_module.engine.on_arrival(e) if e.kind == "arrival"
         else app_module.engine.on_vitals(e))
    yield TestClient(app_module.app), app_module
    app_module._replay, app_module.engine = original_replay, original_engine


def _login(client, username: str) -> dict[str, str]:
    r = client.post("/v1/auth/token",
                    data={"username": username, "password": username})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_clinical_endpoints_refuse_an_anonymous_caller(api):
    client, _ = api
    for method, path in [("get", "/v1/queue"), ("get", "/v1/history"),
                         ("post", "/v1/encounters/1/nurse-assessments?esi=3"),
                         ("post", "/api/override/1/2")]:
        r = getattr(client, method)(path)
        assert r.status_code == 401, f"{path} answered {r.status_code}"


def test_a_bad_password_is_refused_and_says_nothing_useful(api):
    client, _ = api
    wrong = client.post("/v1/auth/token",
                        data={"username": "nurse.demo", "password": "hunter2"})
    unknown = client.post("/v1/auth/token",
                          data={"username": "nobody", "password": "hunter2"})
    assert wrong.status_code == unknown.status_code == 401
    # Identical wording: a different message would enumerate valid usernames.
    assert wrong.json() == unknown.json()


def test_a_role_cannot_exceed_itself(api):
    """An auditor reads the trail. An auditor does not triage."""
    client, _ = api
    auditor = _login(client, "audit.demo")
    assert client.get("/v1/history", headers=auditor).status_code == 200
    assert client.get("/v1/queue", headers=auditor).status_code == 403
    assert client.post("/v1/encounters/1/nurse-assessments?esi=3",
                       headers=auditor).status_code == 403

    ops = _login(client, "ops.demo")
    assert client.get("/v1/operations/forecast", headers=ops).status_code == 200
    # Ops runs the department's flow; lowering a patient's urgency is clinical.
    assert client.post("/api/override/1/4", headers=ops).status_code == 403


def test_the_audit_names_the_person_who_signed_in(api):
    """
    Identity comes from the token, not from a query parameter. An override the
    caller can sign with any name they like is not evidence of anything.
    """
    client, app_module = api
    doc = _login(client, "doc.demo")
    stay = next(iter(app_module.engine.patients))

    assert client.post(f"/api/override/{stay}/4?reason_code=clinically_well",
                       headers=doc).status_code == 200
    # as_rows flattens the payload alongside the chain columns
    entry = [r for r in app_module.engine.audit.as_rows(50)
             if r["kind"] == "override"][-1]
    assert entry["clinician"] == "doc.demo"


def test_an_expired_token_is_refused(api):
    client, _ = api
    import jwt
    from datetime import datetime, timedelta, timezone
    stale = jwt.encode(
        {"sub": "nurse.demo", "role": "nurse",
         "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        auth.SECRET, algorithm=auth.ALGORITHM)
    r = client.get("/v1/queue", headers={"Authorization": f"Bearer {stale}"})
    assert r.status_code == 401 and "expired" in r.json()["detail"]


def test_a_token_signed_with_another_key_is_refused(api):
    client, _ = api
    import jwt
    forged = jwt.encode({"sub": "admin.demo", "role": "admin"},
                        "not-the-secret", algorithm="HS256")
    assert client.get("/v1/queue",
                      headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_passwords_are_hashed_and_salted():
    a, b = auth.hash_password("same"), auth.hash_password("same")
    assert a != b, "identical hashes mean the salt is not being used"
    assert "same" not in a
    assert auth.verify_password("same", a) and not auth.verify_password("Same", a)


# --- the frozen model artifact -----------------------------------------------

def test_a_tampered_artifact_is_not_loaded(monkeypatch, tmp_path):
    """
    Prefer training from scratch over loading a model the manifest does not
    describe. A wrong model that runs is worse than a slow start.
    """
    from ml import artifact

    scorer = AcuityScorer().fit(generate(400, seed=3))
    monkeypatch.setattr(artifact, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(artifact, "MODEL_FILE", tmp_path / "acuity.pkl")
    monkeypatch.setattr(artifact, "MANIFEST_FILE", tmp_path / "manifest.json")

    m = artifact.save(scorer, source="test", training_files=[])
    assert artifact.load() is not None
    assert m["n_features"] == len(scorer.columns)
    assert m["model_version"] == scorer.model_version

    artifact.MODEL_FILE.write_bytes(pickle.dumps(AcuityScorer()))
    assert artifact.load() is None, "bytes not matching the manifest must be refused"


def test_the_manifest_records_what_a_reviewer_needs(monkeypatch, tmp_path):
    from ml import artifact
    monkeypatch.setattr(artifact, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(artifact, "MODEL_FILE", tmp_path / "acuity.pkl")
    monkeypatch.setattr(artifact, "MANIFEST_FILE", tmp_path / "manifest.json")

    m = artifact.save(AcuityScorer().fit(generate(400, seed=3)), source="synthetic")
    for key in ("model_version", "trained_on", "features", "operating_point",
                "conformal_alpha", "metrics", "sha256"):
        assert key in m, f"manifest is missing {key}"
    assert "race" not in m["features"] and "acuity" not in m["features"]


def test_sign_off_records_the_model_version():
    """An override is only reviewable if the model it disagreed with is named."""
    scorer = AcuityScorer().fit(generate(400, seed=3))
    scorer.model_version = "acuity-test-1"
    q = QueueEngine(scorer, slots=0)
    for e in build_events(generate(6, seed=5)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)

    stay = next(iter(q.patients))
    q.nurse_assess(stay, 3)
    q.reveal(stay, token=q.workflow.open(stay).reveal_token)
    q.finalise(stay, clinician="doc.demo", reason_code="agree")
    entry = [r for r in q.audit.as_rows(50) if r["kind"] == "sign_off"][-1]
    assert entry["model_version"] == "acuity-test-1"


# --- shadow mode -------------------------------------------------------------

def _shadow_engine(n: int = 20):
    q = QueueEngine(AcuityScorer().fit(generate(400, seed=3)), slots=0)
    q.shadow = True
    for e in build_events(generate(n, seed=5)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    return q


def test_shadow_mode_changes_nobody_but_the_red_flagged():
    """
    Every band on the board is the baseline. The one exception is a Layer 0 red
    flag, which is a cited threshold rather than a model output — withholding it
    would mean not acting on a measured SpO2 of 84% to keep an experiment clean.
    """
    q = _shadow_engine()
    for p in q.patients.values():
        expected = shadow_mode.baseline_band(p.red_flag)
        assert p.band == expected, f"{p.ticket} sits at {p.band}, not {expected}"


def test_shadow_mode_still_records_what_it_would_have_done():
    q = _shadow_engine()
    rows = [r for r in q.audit.as_rows(500)
            if r["kind"] == "shadow_recommendation"]
    assert rows, "shadow mode recorded nothing"
    assert any(r["shadow_band"] != r["acted_band"]
               for r in rows), "no disagreement to learn from"

    report = shadow_mode.compare(q.audit.as_rows(500))
    assert report["n"] == len(rows)
    assert 0.0 <= report["agreement_rate"] <= 1.0
    assert report["would_have_escalated"] + report["would_have_lowered"] \
        + round(report["agreement_rate"] * report["n"]) == pytest.approx(report["n"], abs=1)


def test_shadow_mode_does_not_escalate_on_trajectory():
    """Layer 2 watches and writes it down. It does not move anyone."""
    q = _shadow_engine(n=25)
    bands = {sid: p.band for sid, p in q.patients.items()}
    for e in build_events(generate(25, seed=5)):
        if e.kind != "arrival" and e.stay_id in q.patients:
            assert q.on_vitals(e) is None, "shadow mode returned a live escalation"
    for sid, p in q.patients.items():
        assert p.band == bands[sid], f"{p.ticket} moved while ATRIA was shadowing"


def test_leaving_shadow_mode_lets_the_layers_act_again():
    q = _shadow_engine()
    q.shadow = False
    e = next(ev for ev in build_events(generate(6, seed=9)) if ev.kind == "arrival")
    q.on_arrival(e)
    p = q.patients[e.stay_id]
    assert p.band == p.shadow_band, "recommendation not applied outside shadow mode"


def test_the_shadow_report_reads_only_the_audit_trail():
    """Reproducible from the record months later, not from live objects."""
    q = _shadow_engine()
    rows = q.audit.as_rows(500)
    assert shadow_mode.compare(rows) == shadow_mode.compare(rows)
    assert shadow_mode.compare([])["n"] == 0


# --- FHIR --------------------------------------------------------------------

def test_fhir_reports_missing_vitals_explicitly():
    """
    "Nobody measured SpO2" and "SpO2 is fine" are different facts, and the
    safety layers depend on the difference.
    """
    from service import fhir_client

    parsed = fhir_client.parse_observations([
        {"resourceType": "Observation",
         "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
         "valueQuantity": {"value": 118}, "effectiveDateTime": "2026-01-01T10:05:00Z"},
        {"resourceType": "Observation",     # older duplicate, must not win
         "code": {"coding": [{"code": "8867-4"}]},
         "valueQuantity": {"value": 70}, "effectiveDateTime": "2026-01-01T08:00:00Z"},
        {"resourceType": "Patient", "id": "ignored"},
    ])
    assert parsed["vitals"] == {"heartrate": 118.0}
    assert "o2sat" in parsed["missing"] and "heartrate" not in parsed["missing"]


def test_fhir_is_not_connected_until_it_is_configured(monkeypatch):
    """An unconfigured integration says so; it does not raise into triage."""
    from service import fhir_client
    monkeypatch.setattr(fhir_client, "BASE", "")
    h = fhir_client.health()
    assert h["connected"] is False and "ATRIA_FHIR_BASE" in h["note"]
    with pytest.raises(fhir_client.FHIRUnavailable):
        fhir_client._get("Patient/1")


def test_a_durable_log_is_not_swapped_for_an_empty_one(db_path):
    """
    Regression. `audit or AuditLog()` looks harmless and is not: AuditLog
    defines __len__, so a fresh durable log is falsy and was being replaced by
    an in-memory one. The service started, printed that it was writing to disk,
    and wrote nothing — found end-to-end, never by a unit test, because every
    unit test passed no log at all.
    """
    durable = AuditLog(store=AuditStore(db_path))
    assert len(durable) == 0 and not durable, "precondition: an empty log is falsy"

    q = QueueEngine(audit=durable, slots=0)
    assert q.audit is durable

    for e in build_events(generate(4, seed=5)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    assert len(AuditLog(store=AuditStore(db_path))) > 0, "nothing reached the disk"
