"""Function tools exposed to agents. Thin wrappers over guardian.data and guardian.scoring."""

import json
from datetime import datetime

from agents import function_tool

from guardian import data, scoring


@function_tool
def get_commitment() -> str:
    """Return the meeting the user must not miss, with deadline and value."""
    return data.load_commitment().model_dump_json()


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
def search_alternative_trips() -> str:
    """Search alternative itineraries to the meeting city (Kiwi/Duffel in live mode)."""
    return json.dumps([o.model_dump(mode="json") for o in data.load_alternatives()])


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
def rank_options() -> str:
    """Deterministically score the current trip and all alternatives.

    Returns options sorted by expected loss (lower is better) with P(on time).
    Always call this before recommending; never compute scores yourself.
    """
    return json.dumps(compute_ranking())
