"""
The live service — replay clock in, websocket out.

Run:  make demo      (then open http://127.0.0.1:8000)
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Form, WebSocket, WebSocketDisconnect
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from data.loaders.synthetic import generate
from layer1.model import AcuityScorer
from ml import artifact
from service.clock import ReplayClock, build_events
from service import forecast as flow
from service import auth
from service import fhir_client
from service import shadow as shadow_mode
from service.auth import Principal, requires
from service.queue import QueueEngine
from layer3.audit import AuditLog
from layer3.store import AuditStore
from layer3.workflow import BlindAssessmentError

DASHBOARD = Path("dashboard/index.html")
GUIDE = Path("dashboard/guide.html")

app = FastAPI(title="ATRIA", version="0.2.0")

# The Next.js client is served from a different origin in development and from
# Vercel in production. Origins are listed rather than wildcarded: this API
# mutates clinical state, so it should never accept a cross-origin write from
# somewhere nobody has named.
# Next falls back to 3001, 3002... when 3000 is taken, and a nurse-facing demo
# should not fail with an opaque 400 because of a port collision. The local dev
# range is allowed by default; production origins come from the environment.
_DEV_ORIGINS = [
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1")
    for port in (3000, 3001, 3002, 3100)
]
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get(
        "ATRIA_ALLOWED_ORIGINS", ",".join(_DEV_ORIGINS)).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=True,
    allow_methods=["GET", "POST"], allow_headers=["*"],
)
#: The demo shift. Tunable from the environment so a rehearsal does not need a
#: code change.
#:
#: The defaults were chosen after watching the old ones fail a demo. At 240x a
#: three-hour shift lasted 45 seconds, and the seed came from the clock — so
#: every 51 seconds the board wiped and refilled with forty different people
#: while reusing the same ticket numbers. A-13 was a different patient each
#: time you looked. Nothing could be narrated, and nothing could be verified.
DEMO_SPEED = float(os.environ.get("ATRIA_DEMO_SPEED", "30"))      # ~6 min shift
DEMO_SEED = int(os.environ.get("ATRIA_DEMO_SEED", "7"))           # same cast
DEMO_PATIENTS = int(os.environ.get("ATRIA_DEMO_PATIENTS", "100"))
DEMO_HOURS = float(os.environ.get("ATRIA_DEMO_HOURS", "3"))

#: Treatment bays. Adjustable from the board, because how many bays are open is
#: an operational fact that changes during a shift, not a constant.
#:
#: Five against a hundred arrivals is a department under real pressure, which is
#: the state worth demonstrating: the queue builds, and the order ATRIA puts it
#: in starts to matter. Open more bays from the board to watch it drain.
DEMO_SLOTS = int(os.environ.get("ATRIA_DEMO_SLOTS", "5"))

#: Ceiling on what the board may open, so a stray click cannot make the queue
#: vanish and take the demonstration with it.
MAX_SLOTS = 20

#: ATRIA_DB points the audit trail at a SQLite file that outlives the process.
#: Unset means in-memory, which is right for a test and wrong for a deployment,
#: so the startup banner says which one is in force.
_DB = os.environ.get("ATRIA_DB", "")
engine = QueueEngine(audit=AuditLog(store=AuditStore(_DB)) if _DB else None,
                     slots=DEMO_SLOTS)
clients: set[WebSocket] = set()


@app.on_event("startup")
async def startup() -> None:
    # Printed because a rejected preflight surfaces as a bare 400 with no
    # explanation, and the cause is almost always an origin nobody listed.
    print(f"ATRIA: accepting browser requests from {', '.join(ALLOWED_ORIGINS)}")
    print(auth.startup_notice())
    print(f"ATRIA: audit trail -> {_DB}" if _DB else
          "ATRIA: audit trail in memory only — set ATRIA_DB to keep it")
    if engine.shadow:
        print("ATRIA: SHADOW MODE — every layer runs, nothing acts on the board")
    print(f"ATRIA: demo shift = {DEMO_PATIENTS} patients over {DEMO_HOURS:g}h at "
          f"{DEMO_SPEED:g}x (~{DEMO_HOURS * 3600 / DEMO_SPEED / 60:.0f} min real), "
          f"{DEMO_SLOTS} bays, seed {DEMO_SEED}")
    engine.scorer = artifact.load_or_train(
        lambda: AcuityScorer().fit(generate(1500, seed=3)))
    asyncio.create_task(_replay())


#: How many patients the demo leaves at the top of the queue for the human.
#: The simulated colleagues work from the tail, so the person using the board is
#: never racing them for the patient they are about to open — that was the
#: "record changed under me" bug, and it is not worth reintroducing for a demo.
HUMAN_HEADROOM = int(os.environ.get("ATRIA_DEMO_HEADROOM", "6"))


def _simulated_colleagues() -> None:
    """
    Other nurses, working the same shift.

    A patient must be triaged before a bay will take them, which is correct and
    leaves a one-person demo with an empty department: a hundred arrivals, one
    human, and nothing ever reaching treatment. So the rest of the team is
    simulated.

    They work from the BOTTOM of the queue and never touch the top few, so the
    patient the user is about to open is always theirs. Every sign-off goes
    through the real workflow and lands in the audit under a name that says it
    was simulated, because a trail that quietly mixes real and synthetic
    decisions is worse than one that is obviously synthetic.
    """
    waiting_for_bay = sum(1 for p in engine.patients.values() if p.signed_off)
    if waiting_for_bay >= engine.slots:
        return                                  # bays are already fed

    unassessed = [(k, v) for k, v in engine.patients.items()
                  if not v.signed_off and not engine.mid_assessment(k)]
    if len(unassessed) <= HUMAN_HEADROOM:
        return                                  # leave the rest to the human

    # Same order the board shows, so "the tail" means the same thing to both.
    unassessed.sort(key=lambda kv: (kv[1].band, -kv[1].waited(engine.now)))

    # Walk on past anyone who refuses rather than stopping at them. The list is
    # sorted, so retrying only the first two meant that if those two happened to
    # be unassessable the colleagues picked the same pair on every event and
    # never signed anybody off again for the rest of the shift.
    done = 0
    for stay_id, patient in unassessed[HUMAN_HEADROOM:]:
        if done >= 2:
            break
        try:
            stored = engine.nurse_assess(stay_id, patient.band)
            engine.reveal(stay_id, token=stored.get("reveal_token"))
            engine.finalise(stay_id, clinician="nurse.sim (simulated colleague)",
                            reason_code="reassessed_at_bedside")
            done += 1
        except Exception:
            # A simulated colleague must never be able to stop the shift.
            continue


async def _replay(speed: float | None = None, surge: float = 1.0) -> None:
    """
    Replay one synthetic shift on loop, so the board is never empty.

    The seed is fixed. Every cycle brings back the same hundred patients in the
    same order, which is what makes a demo rehearsable and a bug reproducible.
    Set ATRIA_DEMO_SEED to vary it.
    """
    speed = DEMO_SPEED if speed is None else speed
    while True:
        # One call, so a new piece of per-shift state cannot be forgotten here.
        engine.reset_shift()
        ds = generate(DEMO_PATIENTS, seed=DEMO_SEED, hours=DEMO_HOURS)
        clock = ReplayClock(build_events(ds, surge=surge), speed=speed)
        async for event in clock.stream():
            if event.kind == "arrival":
                engine.on_arrival(event)
            else:
                engine.on_vitals(event)
            _simulated_colleagues()
            await _broadcast()
        await asyncio.sleep(6)


async def _broadcast() -> None:
    if not clients:
        return
    payload = json.dumps(engine.snapshot(), default=str)
    for ws in list(clients):
        try:
            await ws.send_text(payload)
        except Exception:
            clients.discard(ws)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(DASHBOARD)


@app.get("/guide")
async def guide() -> FileResponse:
    """The full operating guide — how to run it, what to click, what it all means."""
    return FileResponse(GUIDE)


# --- authentication ---------------------------------------------------------

@app.post("/v1/auth/token")
async def token(form: OAuth2PasswordRequestForm = Depends()) -> JSONResponse:
    """Exchange credentials for a bearer token."""
    principal = auth.authenticate(form.username, form.password)
    if principal is None:
        # One message for both failure modes: distinguishing them tells an
        # attacker which usernames exist.
        return JSONResponse({"error": "incorrect username or password"},
                            status_code=401,
                            headers={"WWW-Authenticate": "Bearer"})
    return JSONResponse(auth.issue_token(principal))


@app.post("/v1/auth/identify")
async def identify(name: str = Form(...)) -> JSONResponse:
    """
    Sign in with a name or employee ID and no password.

    The token this returns is marked unverified and carries the nurse role
    only, so nobody can declare themselves an administrator on the way in. Every
    entry it produces is written to the record as "(self-declared)".
    """
    if not auth.OPEN_SIGN_IN:
        return JSONResponse({"error": "this deployment requires a password"},
                            status_code=403)
    try:
        principal = auth.identify(name)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    return JSONResponse(auth.issue_token(principal))


@app.get("/v1/auth/mode")
async def auth_mode() -> JSONResponse:
    """
    Is authentication on, and are the demo accounts live?

    Deliberately public and deliberately separate from /me. The board has to ask
    this before it can know whether to show a sign-in screen, and asking /me
    without a token answered 401 — so every visit opened with a red error in the
    console. Console noise on a normal page load is not harmless: it is where a
    real error goes to hide.
    """
    return JSONResponse({"auth_enabled": auth.AUTH_ENABLED,
                         "demo_accounts": auth.DEMO_MODE,
                         "open_sign_in": auth.OPEN_SIGN_IN})


@app.get("/v1/auth/me")
async def me(user: Principal = Depends(auth.current_user)) -> JSONResponse:
    """Who the browser is signed in as, and what that role may do."""
    return JSONResponse({**user.as_dict(), "auth_enabled": auth.AUTH_ENABLED,
                         "demo_accounts": auth.DEMO_MODE})


@app.get("/api/snapshot")
async def snapshot(user: Principal = Depends(requires("queue:read"))) -> JSONResponse:
    return JSONResponse(json.loads(json.dumps(engine.snapshot(), default=str)))


@app.post("/api/degraded/{on}")
async def degraded(on: int,
                   user: Principal = Depends(requires("demo:write"))) -> dict:
    """Scenario 06: kill the model, prove Layer 0 keeps gating."""
    engine.degraded = bool(on)
    await _broadcast()
    return {"degraded": engine.degraded}


@app.post("/api/override/{stay_id}/{band}")
async def override(stay_id: int, band: int,
                   reason_code: str = "clinical_judgement",
                   user: Principal = Depends(requires("override:write"))) -> dict:
    """band 0 means accept the recommendation as-is and sign off."""
    if band == 0:
        band = engine.patients[stay_id].band
    # Identity comes from the token, never from the request body. An audit
    # entry a caller can name themselves in is not evidence.
    entry = engine.override(stay_id, band, reason_code, clinician=user.audit_name)
    await _broadcast()
    return entry


@app.get("/api/audit")
async def audit(limit: int = 60,
                user: Principal = Depends(requires("history:read"))) -> JSONResponse:
    intact, note = engine.audit.verify()
    return JSONResponse({
        "intact": intact, "note": note, "entries": len(engine.audit),
        "rows": json.loads(json.dumps(engine.audit.as_rows(limit), default=str)),
    })


# --- patient check-in and vitals (PRD §16.2) --------------------------------

@app.post("/v1/encounters")
async def create_encounter(stay_id: int, age: float | None = None,
                           gender: str | None = None,
                           chiefcomplaint: str = "unspecified",
                           arrival_transport: str = "walk-in",
                           user: Principal = Depends(requires("intake:write"))
                           ) -> JSONResponse:
    """Check in a new patient. In demo mode, arrivals come from the replay clock;
    this endpoint lets external integrations and the acceptance test suite inject
    patients directly."""
    from service.clock import Event
    import pandas as _pd

    payload = dict(age=age, gender=gender, chiefcomplaint=chiefcomplaint,
                   arrival_transport=arrival_transport)
    now = engine.now or _pd.Timestamp.now()
    event = Event(at=now, kind="arrival", stay_id=stay_id, payload=payload)
    engine.on_arrival(event)
    await _broadcast()
    p = engine.patients.get(stay_id)
    if p is None:
        return JSONResponse({"error": "patient not found after check-in"}, status_code=500)
    return JSONResponse(p.as_dict(now))


@app.post("/v1/encounters/{stay_id}/observations")
async def submit_observation(stay_id: int,
                             heartrate: float | None = None,
                             resprate: float | None = None,
                             o2sat: float | None = None,
                             sbp: float | None = None,
                             dbp: float | None = None,
                             temperature: float | None = None,
                             user: Principal = Depends(requires("intake:write")),
                             ) -> JSONResponse:
    """Submit a vitals observation for a checked-in patient."""
    import pandas as _pd
    from service.clock import Event

    now = engine.now or _pd.Timestamp.now()
    payload = dict(stay_id=stay_id, charttime=now,
                   heartrate=heartrate, resprate=resprate, o2sat=o2sat,
                   sbp=sbp, dbp=dbp, temperature=temperature)
    event = Event(at=now, kind="vitals", stay_id=stay_id, payload=payload)
    result = engine.on_vitals(event)
    await _broadcast()
    return JSONResponse(result or {"status": "recorded"})


# --- REA-008: charge-nurse acknowledgement -----------------------------------

@app.post("/v1/charge-nurse/{stay_id}/acknowledge")
async def charge_nurse_ack(
        stay_id: int,
        user: Principal = Depends(requires("acknowledge:write"))) -> JSONResponse:
    """The charge nurse acknowledges an overdue reassessment alert (REA-008)."""
    p = engine.patients.get(stay_id)
    if p is None:
        return JSONResponse({"error": "patient not found"}, status_code=404)
    engine.audit.append(
        "charge_nurse_acknowledgement", stay_id, engine.now,
        clinician=user.audit_name, band=p.band,
        overdue_by=round(p.overdue_by),
    )
    # Clear the escalation flag so it doesn't re-fire
    if hasattr(p, '_charge_escalated'):
        p._charge_escalated = False
    await _broadcast()
    return JSONResponse({"status": "acknowledged", "stay_id": stay_id,
                         "clinician": user.audit_name})



# --- blind nurse-first assessment (PRD 16.2) --------------------------------

@app.post("/v1/encounters/{stay_id}/nurse-assessments")
async def nurse_assessment(
        stay_id: int, esi: int,
        user: Principal = Depends(requires("assess:write"))) -> JSONResponse:
    """Store the nurse's blind ESI. Returns no recommendation."""
    try:
        return JSONResponse(engine.nurse_assess(stay_id, esi))
    except (BlindAssessmentError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


@app.get("/v1/assessments/{stay_id}")
async def read_assessment(
        stay_id: int,
        user: Principal = Depends(requires("assess:write"))) -> JSONResponse:
    """
    The current state of one assessment, without advancing it.

    Safe by construction rather than by care: this returns exactly what
    `visible_to_nurse()` returns, and that method omits the recommendation until
    the nurse has committed. There is no branch here that could leak it early
    because there is no recommendation in the payload to leak.
    """
    return JSONResponse(engine.workflow.open(stay_id).visible_to_nurse())


@app.post("/v1/assessments/{stay_id}/reveal")
async def reveal(stay_id: int, reveal_token: str = "",
                 user: Principal = Depends(requires("assess:write"))) -> JSONResponse:
    """
    Reveal ATRIA. Refuses if the nurse has not committed.

    The token comes from the nurse-assessment response. Requiring it means a
    reveal cannot be produced by a client that skips or reorders the flow.
    """
    try:
        payload = engine.reveal(stay_id, token=reveal_token or None)
    except BlindAssessmentError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    await _broadcast()
    return JSONResponse(payload)


@app.post("/v1/assessments/{stay_id}/finalize")
async def finalize(
        stay_id: int, reason_code: str = "", reason_note: str = "",
        user: Principal = Depends(requires("assess:write"))) -> JSONResponse:
    try:
        payload = engine.finalise(stay_id, clinician=user.audit_name,
                                  reason_code=reason_code, reason_note=reason_note)
    except BlindAssessmentError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    await _broadcast()
    return JSONResponse(payload)


@app.post("/v1/encounters/{stay_id}/worsening")
async def worsening(
        stay_id: int,
        user: Principal = Depends(requires("worsening:write"))) -> JSONResponse:
    """Report a change. Clears sign-off and forces a fresh blind cycle."""
    payload = engine.report_change(stay_id, reporter=user.audit_name)
    await _broadcast()
    return JSONResponse(payload)


# --- shadow mode ------------------------------------------------------------

@app.get("/v1/shadow")
async def shadow_report(
        user: Principal = Depends(requires("history:read"))) -> JSONResponse:
    """How often ATRIA would have disagreed, while changing nothing."""
    return JSONResponse({
        "enabled": engine.shadow,
        "baseline_band": shadow_mode.SHADOW_BASELINE,
        **shadow_mode.compare(engine.audit.as_rows(limit=5000)),
    })


@app.post("/v1/shadow/{on}")
async def set_shadow(on: int,
                     user: Principal = Depends(requires("admin:write"))) -> dict:
    """
    Switch shadow mode. Audited, because going live is a clinical decision.
    """
    engine.shadow = bool(on)
    engine.audit.append("shadow_mode_changed", 0, engine.now,
                        enabled=engine.shadow, clinician=user.audit_name)
    await _broadcast()
    return {"shadow": engine.shadow}


@app.post("/v1/operations/bays/{count}")
async def set_bays(count: int,
                   user: Principal = Depends(requires("ops:write"))) -> JSONResponse:
    """
    Open or close treatment bays.

    Closing a bay never turns anyone out: capacity is checked when the next
    patient is pulled in, so people already being treated finish. It is an
    operational change and it is audited like one.
    """
    count = max(0, min(MAX_SLOTS, count))
    before, engine.slots = engine.slots, count
    engine.audit.append("bays_changed", 0, engine.now,
                        frm=before, to=count, clinician=user.audit_name)
    await _broadcast()
    return JSONResponse({"slots": engine.slots, "in_treatment": len(engine.in_treatment),
                         "max": MAX_SLOTS})


@app.get("/v1/queue")
async def queue(user: Principal = Depends(requires("queue:read"))) -> JSONResponse:
    return JSONResponse(json.loads(json.dumps(engine.snapshot(), default=str)))


@app.get("/v1/operations/forecast")
async def operations_forecast(
        nurses: int = 6, spaces: int = 20, arrivals: float = 13.0,
        user: Principal = Depends(requires("ops:read"))) -> JSONResponse:
    snap = engine.snapshot()
    out = flow.project(flow.FlowInputs(
        waiting=snap["waiting"], inside=snap["in_treatment"], nurses=nurses,
        arrival_rate_per_hour=arrivals, physical_spaces=spaces))
    return JSONResponse(out.as_dict())


@app.get("/v1/history")
async def history(mode: str = "audit", limit: int = 60,
                  user: Principal = Depends(requires("history:read"))) -> JSONResponse:
    decision_kinds = {"nurse_assessment", "atria_reveal", "sign_off",
                      "override", "worsening_reported", "abstain"}
    rows = engine.audit.as_rows(limit=500)
    if mode == "audit":
        rows = [r for r in rows if r["kind"] in decision_kinds]
    intact, note = engine.audit.verify()
    return JSONResponse({"mode": mode, "intact": intact, "note": note,
                         "events": rows[-limit:]})


#: Two ways of reading the same trail.
#:
#: "atria" is what the machine did on its own: what it scored, what it refused
#: to score, what a safety rule fired on, what a trajectory escalated. "nurse"
#: is what people did to a priority: the blind choice, the sign-off, an
#: override, a reported change.
#:
#: Splitting them is not cosmetic. The question "what did ATRIA do" and the
#: question "what did we do about it" have different audiences, and mixing them
#: is how a reviewer loses the thread.
LOG_VIEWS = {
    "atria": {"arrival", "abstain", "escalation", "atria_reveal",
              "charge_nurse_escalation", "shadow_recommendation"},
    "nurse": {"nurse_assessment", "sign_off", "override", "worsening_reported",
              "charge_nurse_acknowledgement", "bays_changed"},
}


@app.get("/v1/logs")
async def logs(view: str = "atria", limit: int = 120,
               user: Principal = Depends(requires("history:read"))) -> JSONResponse:
    """One of the two views above, newest last, with the chain's own verdict."""
    kinds = LOG_VIEWS.get(view)
    rows = engine.audit.as_rows(limit=2000)
    if kinds is not None:
        rows = [r for r in rows if r["kind"] in kinds]
    intact, note = engine.audit.verify()
    return JSONResponse({
        "view": view, "views": sorted(LOG_VIEWS), "intact": intact, "note": note,
        "total": len(engine.audit), "events": rows[-limit:],
    })


@app.get("/v1/integrations/health")
async def integrations_health(
        user: Principal = Depends(requires("queue:read"))) -> JSONResponse:
    """Freshness and failure state per integration (PRD INT-001)."""
    return JSONResponse({
        "records": {"connected": True, "last_success": str(engine.now)},
        "vitals": {"connected": not engine.degraded, "last_success": str(engine.now)},
        "beds": {"connected": True, "last_success": str(engine.now)},
        "roster": {"connected": True, "last_success": str(engine.now)},
        "model": {"connected": not engine.degraded,
                  "version": engine.model_version},
        "fhir": fhir_client.health(),
    })


@app.get("/v1/integrations/fhir/{patient_id}")
async def fhir_vitals(patient_id: str,
                      user: Principal = Depends(requires("queue:read"))) -> JSONResponse:
    """Pull a patient's vitals from the configured FHIR server. Read-only."""
    try:
        return JSONResponse({"patient": fhir_client.patient(patient_id),
                             **fhir_client.vitals_for(patient_id)})
    except fhir_client.FHIRUnavailable as exc:
        # 503, not 500: the integration is down, ATRIA is not.
        return JSONResponse({"error": str(exc), "connected": False},
                            status_code=503)


@app.post("/v1/integrations/fhir/{patient_id}/admit")
async def fhir_admit(patient_id: str, stay_id: int,
                     user: Principal = Depends(requires("intake:write"))
                     ) -> JSONResponse:
    """
    Pull a patient from FHIR and put them on the board, scored.

    Reading the record and acting on it were two separate steps, and only the
    first existed: /integrations/fhir/{id} returned JSON that a human then had
    to retype into the check-in form. This closes that: fetch, check in, submit
    the vitals as an observation, and let the normal pipeline score them.

    It goes through on_arrival and on_vitals rather than writing to the engine
    directly, so a patient arriving from a hospital record is assessed by
    exactly the same code as one typed in at the desk. Missing vitals stay
    missing — the safety layers depend on knowing what was never measured.
    """
    import pandas as _pd
    from service.clock import Event

    try:
        demographics = fhir_client.patient(patient_id)
        reading = fhir_client.vitals_for(patient_id)
    except fhir_client.FHIRUnavailable as exc:
        return JSONResponse({"error": str(exc), "connected": False},
                            status_code=503)

    age = None
    if born := demographics.get("birth_date"):
        try:
            age = (_pd.Timestamp.now() - _pd.Timestamp(born)).days / 365.25
        except ValueError:
            age = None

    now = engine.now or _pd.Timestamp.now()
    engine.on_arrival(Event(at=now, kind="arrival", stay_id=stay_id, payload=dict(
        age=age, gender=demographics.get("gender"),
        chiefcomplaint=f"from FHIR record {patient_id}",
        arrival_transport="unknown", **reading["vitals"])))

    # A second event, so the reading lands on the trajectory as an observation
    # and the patient is re-scored exactly as any monitored patient would be.
    if reading["vitals"]:
        engine.on_vitals(Event(at=now, kind="vitals", stay_id=stay_id,
                               payload={"stay_id": stay_id, "charttime": now,
                                        **reading["vitals"]}))

    engine.audit.append("fhir_import", stay_id, engine.now,
                        fhir_patient=patient_id, clinician=user.audit_name,
                        vitals_found=sorted(reading["vitals"]),
                        vitals_missing=reading["missing"])
    await _broadcast()

    patient = engine.patients.get(stay_id) or engine.in_treatment.get(stay_id)
    return JSONResponse({
        "stay_id": stay_id, "imported_from": patient_id,
        "vitals_found": reading["vitals"], "missing": reading["missing"],
        "band": patient.band if patient else None,
        "abstained": patient.abstained if patient else None,
    })


@app.websocket("/ws")
async def ws(websocket: WebSocket, token: str = "") -> None:
    """
    The live board.

    Browsers cannot set headers on a WebSocket, so the bearer token arrives as a
    query parameter. It is the same signed token, checked the same way — the
    stream carries the whole queue and is not more public than /v1/queue.
    """
    if auth.AUTH_ENABLED:
        try:
            await auth.current_user(token or None)
        except Exception:
            await websocket.close(code=4401)   # unauthorised
            return
    await websocket.accept()
    clients.add(websocket)
    try:
        await websocket.send_text(json.dumps(engine.snapshot(), default=str))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        clients.discard(websocket)
    except Exception:
        clients.discard(websocket)
