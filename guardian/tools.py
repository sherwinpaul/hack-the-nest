"""Function tools exposed to agents. Thin wrappers over guardian.data and guardian.scoring."""

import asyncio
import json
from datetime import datetime

from agents import function_tool

from guardian import data, scoring
from guardian.airports import tz_for
from guardian.config import settings
from guardian.schemas import ScoredOption


@function_tool
def get_commitment() -> str:
    """Return the meeting the user must not miss, with deadline and value."""
    c = data.load_commitment()
    return json.dumps(
        {**c.model_dump(mode="json"), "must_arrive_by_local": _local(c.must_arrive_by, c.airport)}
    )


def _local(when: datetime, airport: str) -> str:
    """Human time at the airport, e.g. 'Tue Nov 17, 8:30 AM MST' (UTC if the zone is unknown)."""
    tz = tz_for(airport)
    t = when.astimezone(tz) if tz else when
    return t.strftime("%a %b %-d, %-I:%M %p ") + (t.tzname() or "UTC")


@function_tool
def get_current_trip() -> str:
    """Return the user's currently booked itinerary."""
    return data.load_current_trip().model_dump_json()


@function_tool
def get_airport_weather_risk(airport: str, when_iso: str) -> str:
    """Disruption probability for an airport around a time.

    Args:
        airport: IATA code, e.g. ORD.
        when_iso: ISO-8601 datetime of departure/arrival at that airport.
    """
    return data.airport_risk(airport.upper(), datetime.fromisoformat(when_iso)).model_dump_json()


@function_tool
async def search_alternative_trips() -> str:
    """Search alternative itineraries that land before the meeting deadline.

    Live mode queries Kiwi.com (via its MCP server) twice: all flights that arrive in
    time, and the same while never connecting through high-risk hubs.
    """
    if settings().data_mode == "live":
        await data.refresh_live_fares()
    options = data.load_alternatives()
    if not options:
        return "No alternative flights found that arrive before the deadline."
    return json.dumps([_brief(o) for o in options])


def _brief(o) -> dict:
    """Compact view for the LLM: enough to reason about, small enough to stay cheap."""
    return {
        "id": o.id,
        "route": " > ".join(o.airports),
        "flights": [leg.flight_no for leg in o.legs],
        "departs_local": _local(o.legs[0].depart, o.airports[0]),
        "arrives_local": _local(o.arrive, o.airports[-1]),
        "arrives_utc": o.arrive.isoformat(),
        "price_usd": o.price_usd,
        "source": o.source,
    }


async def ensure_live_fares() -> None:
    """Live mode: make sure a Kiwi search has populated the alternatives."""
    if settings().data_mode == "live" and not data.load_alternatives():
        await data.refresh_live_fares()


@function_tool
def get_disruption_news() -> str:
    """Replay-mode stand-in for Exa results: advisories and news about the disruption."""
    return json.dumps([e.model_dump() for e in data.load_intel_fixture()])


def compute_ranking() -> list[dict]:
    """Shared by the rank tool and the --dry CLI path."""
    c = data.load_commitment()
    current = data.load_current_trip()
    options = [current] + data.load_alternatives()
    airports = {a for o in options for a in o.airports}
    risks = [data.airport_risk(a, c.must_arrive_by) for a in sorted(airports)]
    ranked = scoring.rank(options, risks, c, baseline_price=current.price_usd)
    return [s.model_dump(mode="json") for s in ranked]


@function_tool
async def rank_options() -> str:
    """Deterministically score the current trip and all alternatives.

    Returns options sorted by expected loss (lower is better) with P(on time).
    Always call this before recommending; never compute scores yourself.
    """
    await ensure_live_fares()
    ranked = await asyncio.to_thread(compute_ranking)
    return json.dumps(
        [
            {**_brief(ScoredOption.model_validate(r).option), **{k: r[k] for k in RANK_KEYS}}
            for r in ranked[:8]
        ]
    )


RANK_KEYS = ("p_on_time", "expected_loss_usd", "extra_cost_usd")
