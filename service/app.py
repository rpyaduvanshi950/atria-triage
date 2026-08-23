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
from service.queue import QueueEngine

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
