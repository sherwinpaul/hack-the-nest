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

from guardian import booking, data, duffel, kiwi, payments
from guardian.agents_def import build_agents
from guardian.airports import AIRPORT_COORDS, AIRPORTS, CITY
from guardian.config import settings
from guardian.mcp_servers import connect_all
from guardian.models import configure_tracing, describe_routing
from guardian.schemas import ScoredOption, TravelOption
from guardian.tools import compute_ranking, ensure_live_fares
from guardian.trace import TraceHooks

WEB = Path(__file__).parent / "web"

app = FastAPI(title="Trip Guardian")
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.middleware("http")
async def revalidate_static(request, call_next):
    """Make browsers revalidate static files, so an updated app.js is never skipped."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


configure_tracing()
_run_lock = asyncio.Lock()
log = logging.getLogger("guardian.server")


@app.get("/")
def index() -> FileResponse:
    # no-cache: always revalidate, so a new app.js never runs against a stale page
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/state")
async def state(priority: str | None = None) -> dict[str, Any]:
    """Snapshot for the dashboard. Live mode fetches Kiwi fares (cached) first.

    `priority` (price | balanced | reliability) re-ranks instantly, without any LLM call,
    and becomes the traveller's choice for the next guardian run.
    """
    if priority:
        try:
            data.set_priority(priority)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
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
        "priority": data.get_priority(),
        "routing": describe_routing(),
        "coords": {a: AIRPORT_COORDS.get(a) for a in airports},
        "tz": {a: AIRPORTS[a][2] for a in airports if a in AIRPORTS},
        "cities": {a: CITY.get(a, a) for a in airports},
        "commitment": c.model_dump(mode="json"),
        "current_trip": trip.model_dump(mode="json"),
        "risks": {
            a: data.airport_risk(a, c.must_arrive_by).model_dump(mode="json")
            for a in airports
        },
        "ranking": ranking,
        "payments": dict(zip(("enabled", "reason"), payments.enabled(), strict=True)),
    }


class Approval(BaseModel):
    option_id: str


async def _find_option(option_id: str) -> TravelOption:
    for r in await asyncio.to_thread(compute_ranking):
        if r["option"]["id"] == option_id:
            return ScoredOption.model_validate(r).option
    raise HTTPException(404, f"Unknown option {option_id}")


@app.post("/api/approve")
async def approve(body: Approval) -> dict[str, str]:
    """Hand-off booking: a fresh kiwi.com link in live mode, simulated in replay."""
    option = await _find_option(body.option_id)
    url = ""
    if option.source == "kiwi" and settings().data_mode == "live":
        url = await _fresh_kiwi_link(option)
    return {"status": "ok", "message": booking.book(option), "url": url}


async def _fresh_kiwi_link(option: TravelOption) -> str:
    """Kiwi booking links carry a short-lived token: re-search if ours is old."""
    if kiwi.links_stale():
        await data.refresh_live_fares(force=True)
    sig = [leg.flight_no for leg in option.legs]
    for o in data.load_alternatives():
        if [leg.flight_no for leg in o.legs] == sig and o.booking_ref.startswith("https://"):
            return o.booking_ref
    raise HTTPException(409, "That fare is no longer available on Kiwi.com. Refresh the options.")


class CheckoutRequest(BaseModel):
    option_id: str


class BookRequest(BaseModel):
    checkout_id: str
    passenger: dict[str, str]


@app.post("/api/checkout")
async def checkout(body: CheckoutRequest) -> dict[str, Any]:
    """Start in-app checkout: find and re-price the Duffel offer, create a Stripe payment."""
    option = await _find_option(body.option_id)
    try:
        return await payments.start_checkout(option)
    except payments.CheckoutError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/passenger/validate")
async def validate_passenger(passenger: dict[str, str]) -> dict[str, Any]:
    """Checked before the payment form appears, so nobody pays with unusable details."""
    try:
        return {"ok": True, "passenger": duffel.validate_passenger(passenger)}
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.post("/api/book")
async def book(body: BookRequest) -> dict[str, Any]:
    """After the traveller has paid: verify the payment, then create the airline order."""
    try:
        return await payments.complete_booking(body.checkout_id, body.passenger)
    except payments.CheckoutError as e:
        raise HTTPException(400, str(e)) from e


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
                    "Check my upcoming trip and find the best way to get me to my event on time.",
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
