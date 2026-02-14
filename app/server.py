from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import load_settings
from .telemetry import TelemetryPoller, TelemetryStore

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

settings = load_settings()
store = TelemetryStore(settings.obd_host, settings.obd_port)
poller = TelemetryPoller(settings, store)

app = FastAPI(title="Pi Digital Dashboard", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/state")
async def api_state() -> dict[str, object]:
    return await store.snapshot()


@app.get("/api/health")
async def api_health() -> dict[str, object]:
    snapshot = await store.snapshot()
    return {
        "status": "ok",
        "connected": snapshot["connected"],
    }


@app.on_event("startup")
async def startup_event() -> None:
    app.state.stop_event = asyncio.Event()
    app.state.poller_task = asyncio.create_task(poller.run(app.state.stop_event))


@app.on_event("shutdown")
async def shutdown_event() -> None:
    stop_event: asyncio.Event = app.state.stop_event
    poller_task: asyncio.Task[None] = app.state.poller_task

    stop_event.set()
    with suppress(asyncio.TimeoutError):
        await asyncio.wait_for(poller_task, timeout=5.0)
    if not poller_task.done():
        poller_task.cancel()
        with suppress(asyncio.CancelledError):
            await poller_task
