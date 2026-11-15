"""Web API + dashboard.

  uv run uvicorn guardian.server:app --reload --port 8000

GET  /api/state    instant snapshot: commitment, trip, airport risks, ranking (no LLM)
GET  /api/run      Server-Sent Events: live agent trace, then the recommendation
POST /api/approve  book the approved option (Duffel test mode / simulated)
"""

import asyncio
import json
import logging
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from agents import Runner
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from guardian import booking, data
from guardian.agents_def import build_agents
from guardian.airports import AIRPORT_COORDS, AIRPORTS
from guardian.config import settings
from guardian.mcp_servers import connect_all
from guardian.models import configure_tracing, describe_routing
from guardian.schemas import ScoredOption
from guardian.tools import compute_ranking, ensure_live_fares
from guardian.trace import TraceHooks

WEB = Path(__file__).parent / "web"

app = FastAPI(title="Trip Guardian")
app.mount("/static", StaticFiles(directory=WEB), name="static")
configure_tracing()
_run_lock = asyncio.Lock()
log = logging.getLogger("guardian.server")


@app.get("/")
def index() -> FileResponse:
    # no-cache: always revalidate, so a new app.js never runs against a stale page
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/state")
async def state() -> dict[str, Any]:
    """Snapshot for the dashboard. Live mode fetches Kiwi fares (cached) first."""
    try:
        await ensure_live_fares()
    except Exception as e:  # noqa: BLE001 — show the board without live fares rather than fail
        log.warning("Live fare search failed: %s", e)
    return await asyncio.to_thread(_build_state)


def _build_state() -> dict[str, Any]:
    c = data.load_commitment()
    trip = data.load_current_trip()
    ranking = compute_ranking()
    airports = sorted({a for r in ranking for a in r["option"]["airports"]})
    return {
        "mode": settings().data_mode,
        "routing": describe_routing(),
        "coords": {a: AIRPORT_COORDS.get(a) for a in airports},
        "tz": {a: AIRPORTS[a][2] for a in airports if a in AIRPORTS},
        "commitment": c.model_dump(mode="json"),
        "current_trip": trip.model_dump(mode="json"),
        "risks": {
            a: data.airport_risk(a, c.must_arrive_by).model_dump(mode="json")
            for a in airports
        },
        "ranking": ranking,
    }


class Approval(BaseModel):
    option_id: str


@app.post("/api/approve")
async def approve(body: Approval) -> dict[str, str]:
    for r in await asyncio.to_thread(compute_ranking):
        if r["option"]["id"] == body.option_id:
            option = ScoredOption.model_validate(r).option
            url = option.booking_ref if option.booking_ref.startswith("https://") else ""
            return {"status": "ok", "message": booking.book(option), "url": url}
    raise HTTPException(404, f"Unknown option {body.option_id}")


# ---------- live agent run (SSE) ----------


class _QueueLogHandler(logging.Handler):
    """Forward key-pool warnings (key switch, model fallback) into the live trace."""

    def __init__(self, q: asyncio.Queue):
        super().__init__(logging.WARNING)
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        self.q.put_nowait(
            {"type": "system", "agent": "Key pool", "text": record.getMessage()}
        )


async def _run_events():
    q: asyncio.Queue = asyncio.Queue()
    handler = _QueueLogHandler(q)
    logging.getLogger("guardian.keypool").addHandler(handler)
    hooks = TraceHooks(q.put_nowait)

    async def worker():
        try:
            async with AsyncExitStack() as stack:
                mcp = await connect_all(stack)
                q.put_nowait(
                    {
                        "type": "system",
                        "agent": "MCP",
                        "text": "connected: " + (", ".join(mcp) or "none (using recorded data)"),
                    }
                )
                agent = build_agents(mcp, hooks=hooks)
                result = await Runner.run(
                    agent,
                    "Check my upcoming trip and protect my meeting.",
                    max_turns=20,
                    hooks=hooks,
                )
                q.put_nowait({"type": "final", "text": str(result.final_output or "")})
        except Exception as e:  # noqa: BLE001 — surface any failure to the UI
            q.put_nowait({"type": "error", "text": f"{type(e).__name__}: {e}"})
        finally:
            q.put_nowait(None)

    task = asyncio.create_task(worker())
    try:
        while (item := await q.get()) is not None:
            yield f"data: {json.dumps(item)}\n\n"
        yield 'data: {"type": "done"}\n\n'
    finally:
        logging.getLogger("guardian.keypool").removeHandler(handler)
        if not task.done():
            task.cancel()


@app.get("/api/run")
async def run() -> StreamingResponse:
    if _run_lock.locked():
        raise HTTPException(409, "A run is already in progress")

    async def locked():
        async with _run_lock:
            async for chunk in _run_events():
                yield chunk

    return StreamingResponse(
        locked(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
