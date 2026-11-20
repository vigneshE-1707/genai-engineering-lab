"""FastAPI app: serves the UI and streams the research swarm over SSE."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from .config import settings
from .graph import graph

app = FastAPI(title="Research Assistant Swarm")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "ok": settings.keys_present,
        "missing_keys": settings.missing_keys(),
        "model": settings.groq_model,
    })


@app.get("/api/research")
async def research(request: Request, q: str = Query(..., min_length=3)) -> EventSourceResponse:
    async def event_gen():
        if not settings.keys_present:
            yield {
                "event": "error",
                "data": json.dumps({
                    "message": "Missing API keys: " + ", ".join(settings.missing_keys())
                                + ". Add them to your .env file."
                }),
            }
            return

        try:
            async for mode, chunk in graph.astream(
                {"query": q, "retries": 0},
                stream_mode=["custom", "updates"],
            ):
                if await request.is_disconnected():
                    break

                if mode == "custom":
                    # progress event emitted by an agent node
                    yield {"event": "progress", "data": json.dumps(chunk)}
                elif mode == "updates":
                    for _node, upd in chunk.items():
                        if isinstance(upd, dict) and upd.get("report"):
                            yield {"event": "report",
                                   "data": json.dumps({"report": upd["report"]})}

            yield {"event": "done", "data": "{}"}
        except Exception as exc:  # noqa: BLE001 - report any failure to the client
            yield {"event": "error", "data": json.dumps({"message": str(exc)})}

    return EventSourceResponse(event_gen())
