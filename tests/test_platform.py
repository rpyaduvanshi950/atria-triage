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


# --- every route, not just the ones someone remembered -----------------------

#: Routes that are meant to be reachable without signing in. The HTML shells
#: carry no patient data — they are empty documents that then have to
#: authenticate — and the token endpoint is how you sign in at all.
PUBLIC_PATHS = {"/", "/guide", "/v1/auth/token", "/v1/auth/me", "/v1/auth/mode",
                "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


def test_no_route_is_accidentally_public(api):
    """
    The guard against the next endpoint. Adding a route to service/app.py and
    forgetting the Depends is a one-line mistake that exposes the whole queue,
    and it would not fail any test that only checks the routes someone thought
    to list here.
    """
    client, app_module = api
    exposed = []
    for route in app_module.app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if path in PUBLIC_PATHS or not methods:
            continue
        # Substitute something harmless for path parameters.
        concrete = path.replace("{stay_id}", "1").replace("{on}", "1") \
                       .replace("{band}", "3").replace("{patient_id}", "x")
        for method in methods & {"GET", "POST"}:
            r = client.request(method, concrete)
            if r.status_code != 401:
                exposed.append(f"{method} {path} -> {r.status_code}")
    assert not exposed, "these answer without a token: " + "; ".join(exposed)


def test_the_served_dashboard_authenticates_every_call(api):
    """
    Regression, and one that shipped. The board served at :8000 called the API
    with no credentials. Once the routes required a token it rendered perfectly
    and then sat empty forever — 401 on every poll, websocket refused, and
    nothing on screen to say why. A page that fails silently is worse than one
    that fails.
    """
    from pathlib import Path
    import re

    html = Path("dashboard/index.html").read_text()

    bare = re.findall(r"[^a-zA-Z]fetch\(\s*[`'\"](/api/|/v1/(?!auth/token))", html)
    assert not bare, f"unauthenticated API calls in the dashboard: {bare}"

    assert "authed(" in html, "the authenticated fetch wrapper is gone"
    assert "?token=" in html, "the websocket must carry the token in the query string"
    assert "4401" in html, "a rejected token must stop the reconnect loop"


def test_asking_whether_auth_is_on_is_not_itself_an_error(api):
    """
    The board has to know whether to show a sign-in screen before it can have a
    token. Answering that with a 401 meant a red console error on every visit,
    which is where a real error goes to hide.
    """
    client, _ = api
    r = client.get("/v1/auth/mode")
    assert r.status_code == 200
    assert set(r.json()) == {"auth_enabled", "demo_accounts"}
    # and it must not leak anything about who exists
    assert "users" not in r.text and "nurse.demo" not in r.text


# --- reading the workflow without advancing it -------------------------------

def test_the_stage_travels_with_the_row(api):
    """
    Without it the board always opened at "choose a priority", and a patient
    part-way through was shown buttons the server then refused with a 409 they
    could do nothing about.
    """
    client, app_module = api
    client.headers.update(_login(client, "nurse.demo"))
    rows = client.get("/v1/queue").json()["rows"]
    assert all("assessment_stage" in r for r in rows)
    assert {r["assessment_stage"] for r in rows} <= {"awaiting_nurse", "compared", "signed"}

    stay = rows[0]["stay_id"]
    client.post(f"/v1/encounters/{stay}/nurse-assessments?esi=3")
    after = next(r for r in client.get("/v1/queue").json()["rows"]
                 if r["stay_id"] == stay)
    assert after["assessment_stage"] == "compared" or after["assessment_stage"] == "awaiting_nurse"


def test_reading_an_assessment_cannot_leak_the_recommendation(api):
    """
    The new GET must not become a way around the blind cycle. It returns what
    visible_to_nurse() returns, and that omits the recommendation until the
    nurse has committed — so there is nothing in the payload to leak.
    """
    client, app_module = api
    client.headers.update(_login(client, "nurse.demo"))
    stay = client.get("/v1/queue").json()["rows"][0]["stay_id"]

    before = client.get(f"/v1/assessments/{stay}")
    assert before.status_code == 200
    body = before.json()
    assert body["stage"] == "awaiting_nurse"
    assert body.get("atria_esi") in (None, "")
    assert "atria_esi" not in before.text or body.get("atria_esi") is None

    # and it does not advance anything: the stage is unchanged afterwards
    assert client.get(f"/v1/assessments/{stay}").json()["stage"] == "awaiting_nurse"


def test_reading_an_assessment_needs_a_role_that_may_assess(api):
    client, _ = api
    nurse = _login(client, "nurse.demo")
    stay = client.get("/v1/queue", headers=nurse).json()["rows"][0]["stay_id"]
    # an auditor reads the trail, not a live assessment
    assert client.get(f"/v1/assessments/{stay}",
                      headers=_login(client, "audit.demo")).status_code == 403


# --- the demo shift ----------------------------------------------------------

def test_the_demo_shift_is_reproducible():
    """
    The old replay seeded from the wall clock, so every cycle brought forty
    different people while reusing the same ticket numbers. A-13 was somebody
    new each time you looked, which makes a demo unrehearsable and a bug
    unreproducible. A fixed seed is the whole fix.
    """
    import service.app as app_module
    from data.loaders.synthetic import generate
    from service.clock import build_events

    a = build_events(generate(app_module.DEMO_PATIENTS, seed=app_module.DEMO_SEED,
                              hours=app_module.DEMO_HOURS))
    b = build_events(generate(app_module.DEMO_PATIENTS, seed=app_module.DEMO_SEED,
                              hours=app_module.DEMO_HOURS))
    assert [e.stay_id for e in a] == [e.stay_id for e in b]
    assert sum(1 for e in a if e.kind == "arrival") == app_module.DEMO_PATIENTS


def test_the_demo_department_is_busy_but_not_stalled():
    """
    The demo runs deliberately short of capacity: five bays against a hundred
    arrivals, so the queue builds and the order ATRIA puts it in starts to
    matter. That is the state worth showing, and the bay control on the board is
    there to relieve it.

    Both bounds still matter. A department that treats almost nobody looks
    broken rather than busy, and one that clears everyone has no queue left to
    demonstrate.
    """
    import service.app as app_module
    from service.queue import TREATMENT_MINUTES

    average_stay = sum(TREATMENT_MINUTES.values()) / len(TREATMENT_MINUTES)
    treated = app_module.DEMO_SLOTS * (app_module.DEMO_HOURS * 60 / average_stay)
    share = treated / app_module.DEMO_PATIENTS
    assert share >= 0.15, f"only {share:.0%} of arrivals get seen; that reads as broken"
    assert share <= 0.95, "no queue left to demonstrate"
    # and the board can relieve it without a restart
    assert app_module.MAX_SLOTS > app_module.DEMO_SLOTS


def test_a_shift_fits_in_a_demo_slot():
    """Long enough to narrate, short enough to loop while someone watches."""
    import service.app as app_module

    minutes = app_module.DEMO_HOURS * 3600 / app_module.DEMO_SPEED / 60
    assert 3 <= minutes <= 15, f"a {minutes:.0f} minute shift is not demoable"


# --- treatment capacity ------------------------------------------------------

def test_only_a_charge_nurse_can_open_or_close_bays(api):
    """
    Capacity is the charge nurse's job in a real department, so it is theirs
    here. A triage nurse sees the count and does not get a button that answers
    403.
    """
    client, _ = api
    assert client.post("/v1/operations/bays/9",
                       headers=_login(client, "nurse.demo")).status_code == 403
    assert client.post("/v1/operations/bays/9",
                       headers=_login(client, "charge.demo")).status_code == 200


def test_bay_count_is_clamped_and_audited(api):
    """A stray click must not make the queue vanish and take the demo with it."""
    import service.app as app_module

    client, engine_module = api
    charge = _login(client, "charge.demo")

    assert client.post("/v1/operations/bays/9999", headers=charge).json()["slots"] \
        == app_module.MAX_SLOTS
    assert client.post("/v1/operations/bays/-5", headers=charge).json()["slots"] == 0

    entries = [r for r in engine_module.engine.audit.as_rows(50)
               if r["kind"] == "bays_changed"]
    assert entries, "a capacity change must be audited"
    assert entries[-1]["clinician"] == "charge.demo"


def test_closing_a_bay_does_not_turn_anybody_out(api):
    """
    Capacity is checked when the next patient is pulled in, so people already
    being treated finish. Ejecting a patient to satisfy a number would be a
    remarkable thing for a triage board to do.
    """
    client, engine_module = api
    engine = engine_module.engine
    charge = _login(client, "charge.demo")

    engine.slots = 5
    for stay_id in list(engine.patients)[:3]:
        out = engine.nurse_assess(stay_id, 3)
        engine.reveal(stay_id, token=out["reveal_token"])
        engine.finalise(stay_id, clinician="nurse.demo", reason_code="agree")
    engine._advance_service()
    treating = len(engine.in_treatment)
    assert treating > 0

    client.post("/v1/operations/bays/0", headers=charge)
    assert len(engine.in_treatment) == treating, "a patient was ejected from a bay"


# --- the two log views -------------------------------------------------------

def test_the_two_log_views_split_the_machine_from_the_people(api):
    """
    "What ATRIA did" and "what we did about it" are different questions with
    different audiences. A single interleaved stream makes both harder to
    follow, so the split exists — but it must be a filter over one chain, never
    two records.
    """
    import service.app as app_module

    client, engine_module = api
    client.headers.update(_login(client, "charge.demo"))

    stay = client.get("/v1/queue").json()["rows"][0]["stay_id"]
    a = client.post(f"/v1/encounters/{stay}/nurse-assessments?esi=3").json()
    client.post(f"/v1/assessments/{stay}/reveal?reveal_token={a['reveal_token']}")
    client.post(f"/v1/assessments/{stay}/finalize?reason_code=reassessed_at_bedside")

    atria = client.get("/v1/logs?view=atria").json()
    nurse = client.get("/v1/logs?view=nurse").json()

    assert {e["kind"] for e in atria["events"]} <= app_module.LOG_VIEWS["atria"]
    assert {e["kind"] for e in nurse["events"]} <= app_module.LOG_VIEWS["nurse"]
    assert not (app_module.LOG_VIEWS["atria"] & app_module.LOG_VIEWS["nurse"]), \
        "an event belongs in one view or the other, not both"

    # a nurse changing a priority must be in the nurse view
    assert any(e["kind"] == "sign_off" for e in nurse["events"])
    # and both views report the same chain
    assert atria["intact"] is nurse["intact"] is True
    assert atria["total"] == nurse["total"] == len(engine_module.engine.audit)


def test_the_logs_are_read_only_and_need_a_role(api):
    """
    A nurse can read the trail, including their own decisions. The rules worth
    enforcing are that an auditor cannot WRITE to it and that ops cannot lower
    a priority; stopping the person who made an entry from reading it back is a
    different thing, and not a useful one.

    Flow coordinators are the exception: they get the department view, not the
    clinical record.
    """
    client, _ = api
    assert client.get("/v1/logs").status_code == 401
    for who in ("nurse.demo", "charge.demo", "doc.demo", "audit.demo"):
        assert client.get("/v1/logs",
                          headers=_login(client, who)).status_code == 200, who
    assert client.get("/v1/logs",
                      headers=_login(client, "ops.demo")).status_code == 403
