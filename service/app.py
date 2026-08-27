"""
The live service — replay clock in, websocket out.

Run:  make demo      (then open http://127.0.0.1:8000)
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from data.loaders.synthetic import generate
from layer1.model import AcuityScorer
from service.clock import ReplayClock, build_events
from service import forecast as flow
from service.queue import QueueEngine
from layer3.workflow import BlindAssessmentError

DASHBOARD = Path("dashboard/index.html")
GUIDE = Path("dashboard/guide.html")

app = FastAPI(title="ATRIA")
engine = QueueEngine()
clients: set[WebSocket] = set()


@app.on_event("startup")
async def startup() -> None:
    engine.scorer = AcuityScorer().fit(generate(1500, seed=3))
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


@app.get("/api/snapshot")
async def snapshot() -> JSONResponse:
    return JSONResponse(json.loads(json.dumps(engine.snapshot(), default=str)))


@app.post("/api/degraded/{on}")
async def degraded(on: int) -> dict:
    """Scenario 06: kill the model, prove Layer 0 keeps gating."""
    engine.degraded = bool(on)
    await _broadcast()
    return {"degraded": engine.degraded}


@app.post("/api/override/{stay_id}/{band}")
async def override(stay_id: int, band: int, reason_code: str = "clinical_judgement") -> dict:
    """band 0 means accept the recommendation as-is and sign off."""
    if band == 0:
        band = engine.patients[stay_id].band
    entry = engine.override(stay_id, band, reason_code, clinician="nurse.demo")
    await _broadcast()
    return entry


@app.get("/api/audit")
async def audit(limit: int = 60) -> JSONResponse:
    intact, note = engine.audit.verify()
    return JSONResponse({
        "intact": intact, "note": note, "entries": len(engine.audit),
        "rows": json.loads(json.dumps(engine.audit.as_rows(limit), default=str)),
    })


# --- blind nurse-first assessment (PRD 16.2) --------------------------------

@app.post("/v1/encounters/{stay_id}/nurse-assessments")
async def nurse_assessment(stay_id: int, esi: int) -> JSONResponse:
    """Store the nurse's blind ESI. Returns no recommendation."""
    try:
        return JSONResponse(engine.nurse_assess(stay_id, esi))
    except (BlindAssessmentError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


@app.post("/v1/assessments/{stay_id}/reveal")
async def reveal(stay_id: int) -> JSONResponse:
    """Reveal ATRIA. Refuses if the nurse has not committed."""
    try:
        payload = engine.reveal(stay_id)
    except BlindAssessmentError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    await _broadcast()
    return JSONResponse(payload)


@app.post("/v1/assessments/{stay_id}/finalize")
async def finalize(stay_id: int, reason_code: str = "",
                   clinician: str = "nurse.demo") -> JSONResponse:
    try:
        payload = engine.finalise(stay_id, clinician=clinician, reason_code=reason_code)
    except BlindAssessmentError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    await _broadcast()
    return JSONResponse(payload)


@app.post("/v1/encounters/{stay_id}/worsening")
async def worsening(stay_id: int, reporter: str = "nurse.demo") -> JSONResponse:
    """Report a change. Clears sign-off and forces a fresh blind cycle."""
    payload = engine.report_change(stay_id, reporter=reporter)
    await _broadcast()
    return JSONResponse(payload)


@app.get("/v1/queue")
async def queue() -> JSONResponse:
    return JSONResponse(json.loads(json.dumps(engine.snapshot(), default=str)))


@app.get("/v1/operations/forecast")
async def operations_forecast(nurses: int = 6, spaces: int = 20,
                              arrivals: float = 13.0) -> JSONResponse:
    snap = engine.snapshot()
    out = flow.project(flow.FlowInputs(
        waiting=snap["waiting"], inside=snap["in_treatment"], nurses=nurses,
        arrival_rate_per_hour=arrivals, physical_spaces=spaces))
    return JSONResponse(out.as_dict())


@app.get("/v1/history")
async def history(mode: str = "audit", limit: int = 60) -> JSONResponse:
    decision_kinds = {"nurse_assessment", "atria_reveal", "sign_off",
                      "override", "worsening_reported", "abstain"}
    rows = engine.audit.as_rows(limit=500)
    if mode == "audit":
        rows = [r for r in rows if r["kind"] in decision_kinds]
    intact, note = engine.audit.verify()
    return JSONResponse({"mode": mode, "intact": intact, "note": note,
                         "events": rows[-limit:]})


@app.get("/v1/integrations/health")
async def integrations_health() -> JSONResponse:
    """Freshness and failure state per integration (PRD INT-001)."""
    return JSONResponse({
        "records": {"connected": True, "last_success": str(engine.now)},
        "vitals": {"connected": not engine.degraded, "last_success": str(engine.now)},
        "beds": {"connected": True, "last_success": str(engine.now)},
        "roster": {"connected": True, "last_success": str(engine.now)},
        "model": {"connected": not engine.degraded},
    })


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
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
