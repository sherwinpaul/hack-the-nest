"""Data access with two modes: `replay` (recorded scenario) and `live` (real APIs).

Replay keeps the stage demo deterministic; live is what the product runs on.
"""

import json
import time
from datetime import datetime
from pathlib import Path

import httpx

from guardian import kiwi
from guardian.airports import AIRPORT_COORDS
from guardian.config import settings
from guardian.schemas import AirportRisk, Commitment, Evidence, TravelOption

SCENARIOS = Path(__file__).resolve().parent.parent / "scenarios"
WEATHER_TTL = 15 * 60
_weather_cache: dict[tuple[str, str], tuple[float, AirportRisk]] = {}


def _scenario() -> dict:
    return json.loads((SCENARIOS / f"{settings().replay_scenario}.json").read_text())


def load_commitment() -> Commitment:
    return Commitment.model_validate(_scenario()["commitment"])


def load_current_trip() -> TravelOption:
    return TravelOption.model_validate(_scenario()["current_trip"])


def load_alternatives() -> list[TravelOption]:
    """Replay: recorded fares. Live: the last Kiwi search (call refresh_live_fares first)."""
    if settings().data_mode == "live":
        return kiwi.cached_options()
    return [TravelOption.model_validate(o) for o in _scenario()["alternatives"]]


async def refresh_live_fares(force: bool = False) -> list[TravelOption]:
    """Live mode: search Kiwi for flights that arrive before the deadline, avoiding risky hubs."""
    c = load_commitment()
    trip = load_current_trip()
    risky = [
        a
        for a in trip.airports[1:-1]
        if airport_risk(a, c.must_arrive_by).disruption_prob >= kiwi.RISKY_HUB_THRESHOLD
    ]
    return await kiwi.search(
        origin=trip.legs[0].origin,
        destination=c.airport,
        arrive_by=c.must_arrive_by,
        avoid_hubs=risky,
        force=force,
    )


def load_intel_fixture() -> list[Evidence]:
    return [Evidence.model_validate(e) for e in _scenario().get("intel", [])]


def airport_risk(airport: str, when: datetime) -> AirportRisk:
    if settings().data_mode == "replay":
        for r in _scenario()["weather"]:
            if r["airport"] == airport:
                return AirportRisk.model_validate(r)
        return AirportRisk(airport=airport, disruption_prob=0.05, reason="no signal")
    key = (airport, when.strftime("%Y-%m-%dT%H"))
    hit = _weather_cache.get(key)
    if hit and time.monotonic() - hit[0] < WEATHER_TTL:
        return hit[1]
    risk = _live_weather_risk(airport, when)
    _weather_cache[key] = (time.monotonic(), risk)
    return risk


def _live_weather_risk(airport: str, when: datetime) -> AirportRisk:
    """Open-Meteo (free, no key). Crude heuristic → disruption probability."""
    if airport not in AIRPORT_COORDS:
        return AirportRisk(airport=airport, disruption_prob=0.05, reason="unknown airport")
    lat, lon = AIRPORT_COORDS[airport]
    day = when.strftime("%Y-%m-%d")
    try:
        resp = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "precipitation,snowfall,wind_gusts_10m,weather_code,visibility",
                "start_date": day,
                "end_date": day,
                "timezone": "UTC",
            },
            timeout=15,
        )
        resp.raise_for_status()
        h = resp.json()["hourly"]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        return AirportRisk(airport=airport, disruption_prob=0.05, reason=f"forecast unavailable ({e})")
    target = when.strftime("%Y-%m-%dT%H:00")
    if target not in h["time"]:
        return AirportRisk(airport=airport, disruption_prob=0.05, reason="outside forecast range")
    i = h["time"].index(target)
    window = slice(max(i - 2, 0), i + 3)

    def vals(name: str) -> list[float]:
        return [v for v in h[name][window] if v is not None] or [0.0]

    gust = max(vals("wind_gusts_10m"))
    snow = sum(vals("snowfall"))
    rain = sum(vals("precipitation"))
    thunder = any(c >= 95 for c in vals("weather_code"))
    vis = min(vals("visibility")) if any(v is not None for v in h["visibility"][window]) else 10_000

    p, reasons = 0.05, []
    if thunder:
        p += 0.45; reasons.append("thunderstorms")
    if snow > 2:
        p += min(snow / 10, 0.5); reasons.append(f"{snow:.1f}cm snow")
    if gust > 55:
        p += 0.2; reasons.append(f"gusts {gust:.0f} km/h")
    if rain > 10:
        p += 0.1; reasons.append(f"{rain:.0f}mm rain")
    if vis < 1600:
        p += 0.15; reasons.append("low visibility")
    return AirportRisk(
        airport=airport,
        disruption_prob=min(p, 0.95),
        reason=", ".join(reasons) or "clear",
    )
