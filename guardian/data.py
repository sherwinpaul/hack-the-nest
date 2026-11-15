"""Data access with two modes: `replay` (recorded scenario) and `live` (real APIs).

Replay keeps the stage demo deterministic; live is what the product runs on.
"""

import json
from datetime import datetime
from pathlib import Path

import httpx

from guardian.config import settings
from guardian.schemas import AirportRisk, Commitment, Evidence, TravelOption

SCENARIOS = Path(__file__).resolve().parent.parent / "scenarios"

# Small lookup for live weather; extend as needed.
AIRPORT_COORDS = {
    "DTW": (42.2124, -83.3534),
    "ORD": (41.9742, -87.9073),
    "MSP": (44.8848, -93.2223),
    "DEN": (39.8561, -104.6737),
    "DFW": (32.8998, -97.0403),
    "ATL": (33.6407, -84.4277),
    "JFK": (40.6413, -73.7781),
    "SFO": (37.6213, -122.3790),
}


def _scenario() -> dict:
    return json.loads((SCENARIOS / f"{settings().replay_scenario}.json").read_text())


def load_commitment() -> Commitment:
    return Commitment.model_validate(_scenario()["commitment"])


def load_current_trip() -> TravelOption:
    return TravelOption.model_validate(_scenario()["current_trip"])


def load_alternatives() -> list[TravelOption]:
    # Live: replace with Kiwi MCP / Duffel offer requests (see guardian/mcp_servers.py).
    return [TravelOption.model_validate(o) for o in _scenario()["alternatives"]]


def load_intel_fixture() -> list[Evidence]:
    return [Evidence.model_validate(e) for e in _scenario().get("intel", [])]


def airport_risk(airport: str, when: datetime) -> AirportRisk:
    if settings().data_mode == "replay":
        for r in _scenario()["weather"]:
            if r["airport"] == airport:
                return AirportRisk.model_validate(r)
        return AirportRisk(airport=airport, disruption_prob=0.05, reason="no signal")
    return _live_weather_risk(airport, when)


def _live_weather_risk(airport: str, when: datetime) -> AirportRisk:
    """Open-Meteo (free, no key). Crude heuristic → disruption probability."""
    if airport not in AIRPORT_COORDS:
        return AirportRisk(airport=airport, disruption_prob=0.05, reason="unknown airport")
    lat, lon = AIRPORT_COORDS[airport]
    resp = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "precipitation,snowfall,wind_gusts_10m,weather_code,visibility",
            "forecast_days": 3,
            "timezone": "UTC",
        },
        timeout=15,
    )
    resp.raise_for_status()
    h = resp.json()["hourly"]
    target = when.strftime("%Y-%m-%dT%H:00")
    i = h["time"].index(target) if target in h["time"] else 0
    window = slice(max(i - 2, 0), i + 3)

    gust = max(h["wind_gusts_10m"][window])
    snow = sum(h["snowfall"][window])
    rain = sum(h["precipitation"][window])
    thunder = any(c >= 95 for c in h["weather_code"][window])
    vis = min(h["visibility"][window])

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
