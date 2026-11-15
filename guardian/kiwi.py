"""Live fares from Kiwi.com's MCP server (search-flight).

The guardian runs two searches in code, not through an LLM, so ranking stays
deterministic:
  1. flights that land before the deadline
  2. the same, never connecting through high-risk hubs
Results are merged, converted to exact UTC times and cached briefly.

Kiwi returns local, zone-less times. The origin's zone anchors the first
departure; every later time is derived from flight durations, so connection
airports need no zone lookup.
"""

import asyncio
import hashlib
import json
import logging
import time
from datetime import UTC, datetime, timedelta

from agents.mcp import MCPServerStreamableHttp, create_static_tool_filter

from guardian.airports import tz_for
from guardian.config import settings
from guardian.schemas import Leg, TravelOption

log = logging.getLogger("guardian.kiwi")

RISKY_HUB_THRESHOLD = 0.4
CACHE_TTL = 10 * 60
MAX_OPTIONS = 12

_cache: dict[str, tuple[float, list[TravelOption]]] = {}
_last: list[TravelOption] = []
_lock = asyncio.Lock()


def cached_options() -> list[TravelOption]:
    return list(_last)


def _flight_no(seg: dict) -> str:
    carrier, number = seg.get("carrier", ""), str(seg.get("flightNumber", ""))
    digits = number.removeprefix(carrier)
    return f"{carrier} {digits}".strip()


def parse_itinerary(it: dict, origin_tz) -> TravelOption | None:
    segs = (it.get("outbound") or {}).get("segments") or []
    if not segs:
        return None
    legs: list[Leg] = []
    offset = None  # local - UTC at the current airport
    for i, seg in enumerate(segs):
        dep_local = datetime.fromisoformat(seg["departureTime"])
        arr_local = datetime.fromisoformat(seg["arrivalTime"])
        if i == 0:
            offset = origin_tz.utcoffset(dep_local)
        dep_utc = dep_local - offset
        arr_utc = dep_utc + timedelta(seconds=int(seg["durationSeconds"]))
        offset = arr_local - arr_utc  # zone of the arrival airport, for the next leg
        legs.append(
            Leg(
                origin=seg["from"],
                destination=seg["to"],
                depart=dep_utc.replace(tzinfo=UTC),
                arrive=arr_utc.replace(tzinfo=UTC),
                carrier=seg.get("carrier", ""),
                flight_no=_flight_no(seg),
            )
        )
    return TravelOption(
        id="kiwi-" + hashlib.sha1(it["id"].encode()).hexdigest()[:10],
        mode="flight",
        legs=legs,
        price_usd=float(it["price"]),
        source="kiwi",
        booking_ref=it.get("bookingUrl", ""),
    )


def _payload(result) -> dict:
    if getattr(result, "structured_content", None):
        return result.structured_content
    text = "".join(getattr(c, "text", "") for c in result.content)
    return json.loads(text)


async def _search_once(server, args: dict, origin_tz) -> list[TravelOption]:
    result = await server.call_tool("search-flight", args)
    if getattr(result, "is_error", False):
        log.warning("Kiwi search failed: %s", str(result.content)[:200])
        return []
    options = []
    for it in _payload(result).get("itineraries", []):
        try:
            if (o := parse_itinerary(it, origin_tz)) is not None:
                options.append(o)
        except (KeyError, ValueError, TypeError) as e:
            log.warning("Skipping unparseable Kiwi itinerary: %s", e)
    return options


async def search(
    origin: str,
    destination: str,
    arrive_by: datetime,
    avoid_hubs: list[str],
    force: bool = False,
) -> list[TravelOption]:
    global _last
    origin_tz, dest_tz = tz_for(origin), tz_for(destination)
    if origin_tz is None or dest_tz is None:
        raise ValueError(f"Unknown time zone for {origin} or {destination}; add it to airports.py")

    key = f"{origin}-{destination}-{arrive_by.isoformat()}-{','.join(sorted(avoid_hubs))}"
    async with _lock:
        hit = _cache.get(key)
        if hit and not force and time.monotonic() - hit[0] < CACHE_TTL:
            _last = hit[1]
            return list(_last)

        dep_day = arrive_by.astimezone(origin_tz).strftime("%d/%m/%Y")
        base = {
            "flyFrom": origin,
            "flyTo": destination,
            "departureDate": dep_day,
            "currency": "USD",
            "atime_to": arrive_by.astimezone(dest_tz).hour,
            "allow_self_transfer": False,  # separate tickets are a bad bet in a disruption
            "allow_overnight_stopovers": False,
            "max_sector_stopovers": 1,
            "sort": "quality",
        }
        searches = [base]
        if avoid_hubs:
            searches.append({**base, "exclude_stopover_airports": ",".join(avoid_hubs)})

        server = MCPServerStreamableHttp(
            name="kiwi",
            params={"url": settings().kiwi_mcp_url},
            client_session_timeout_seconds=90,
            tool_filter=create_static_tool_filter(allowed_tool_names=["search-flight"]),
        )
        async with server:
            batches = await asyncio.gather(
                *(_search_once(server, args, origin_tz) for args in searches)
            )

        merged: dict[tuple, TravelOption] = {}
        for o in (o for batch in batches for o in batch):
            sig = tuple(leg.flight_no for leg in o.legs)
            if sig not in merged or o.price_usd < merged[sig].price_usd:
                merged[sig] = o
        options = sorted(merged.values(), key=lambda o: (o.arrive, o.price_usd))[:MAX_OPTIONS]
        _cache[key] = (time.monotonic(), options)
        _last = options
        log.info("Kiwi returned %d options (avoiding %s)", len(options), avoid_hubs or "none")
        return list(options)
