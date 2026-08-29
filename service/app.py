"""
The live service — replay clock in, websocket out.

Run:  make demo      (then open http://127.0.0.1:8000)
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
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
#: ATRIA_DB points the audit trail at a SQLite file that outlives the process.
#: Unset means in-memory, which is right for a test and wrong for a deployment,
#: so the startup banner says which one is in force.
_DB = os.environ.get("ATRIA_DB", "")
engine = QueueEngine(audit=AuditLog(store=AuditStore(_DB)) if _DB else None)
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
    engine.scorer = artifact.load_or_train(
        lambda: AcuityScorer().fit(generate(1500, seed=3)))
    asyncio.create_task(_replay())


async def _replay(speed: float = 240.0, surge: float = 1.0) -> None:
    """Replay a synthetic shift on loop so the board is never empty."""
    while True:
        engine.patients.clear()
        engine.events_log.clear()
        ds = generate(40, seed=int(asyncio.get_event_loop().time()) % 1000, hours=3.0)
        clock = ReplayClock(build_events(ds, surge=surge), speed=speed)
        async for event in clock.stream():
            if event.kind == "arrival":
                engine.on_arrival(event)
            else:
                engine.on_vitals(event)
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
                         "demo_accounts": auth.DEMO_MODE})


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
                   user: Principal = Depends(requires("admin:write"))) -> dict:
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
    entry = engine.override(stay_id, band, reason_code, clinician=user.username)
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
        clinician=user.username, band=p.band,
        overdue_by=round(p.overdue_by),
    )
    # Clear the escalation flag so it doesn't re-fire
    if hasattr(p, '_charge_escalated'):
        p._charge_escalated = False
    await _broadcast()
    return JSONResponse({"status": "acknowledged", "stay_id": stay_id,
                         "clinician": user.username})



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
        payload = engine.finalise(stay_id, clinician=user.username,
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
    payload = engine.report_change(stay_id, reporter=user.username)
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
                        enabled=engine.shadow, clinician=user.username)
    await _broadcast()
    return {"shadow": engine.shadow}


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
