"""Duffel flights API: find a bookable offer, re-price it, and create an order.

Payment model (Duffel's "collect payments yourself" flow): the traveller pays us
through Stripe, and we pay the airline from our Duffel balance with an instant order.
In test mode the balance is unlimited and offers come from Duffel Airways (ZZ),
Duffel's test airline.
"""

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from guardian.config import settings
from guardian.schemas import TravelOption

API = "https://api.duffel.com"
HEADERS = {"Duffel-Version": "v2", "Accept": "application/json", "Content-Type": "application/json"}


class DuffelError(RuntimeError):
    pass


def _token() -> str:
    token = settings().duffel_access_token
    if not token:
        raise DuffelError("DUFFEL_ACCESS_TOKEN is not set")
    if not token.startswith("duffel_test_"):
        raise DuffelError("Only Duffel test tokens (duffel_test_...) are allowed in this prototype")
    return token


def is_test() -> bool:
    return settings().duffel_access_token.startswith("duffel_test_")


async def _request(method: str, path: str, **kw) -> dict:
    async with httpx.AsyncClient(base_url=API, timeout=60) as client:
        r = await client.request(
            method, path, headers={**HEADERS, "Authorization": f"Bearer {_token()}"}, **kw
        )
    if r.status_code >= 400:
        try:
            errs = r.json().get("errors", [])
            msg = "; ".join(e.get("message", "") for e in errs) or r.text[:300]
        except ValueError:
            msg = r.text[:300]
        raise DuffelError(f"Duffel {r.status_code}: {msg}")
    return r.json()["data"]


def _utc(local: str, tz: str | None) -> datetime:
    dt = datetime.fromisoformat(local)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz) if tz else UTC)
    return dt.astimezone(UTC)


def flight_numbers(offer: dict) -> list[str]:
    segs = offer["slices"][0]["segments"]
    return [
        f"{s['marketing_carrier']['iata_code']} {s['marketing_carrier_flight_number']}" for s in segs
    ]


def summarize(offer: dict) -> dict:
    """What the checkout shows the traveller."""
    segs = offer["slices"][0]["segments"]
    first, last = segs[0], segs[-1]
    return {
        "offer_id": offer["id"],
        "airline": offer["owner"]["name"],
        "airline_code": offer["owner"]["iata_code"],
        "flights": flight_numbers(offer),
        "route": [first["origin"]["iata_code"]] + [s["destination"]["iata_code"] for s in segs],
        "departs": _utc(first["departing_at"], first["origin"].get("time_zone")).isoformat(),
        "arrives": _utc(last["arriving_at"], last["destination"].get("time_zone")).isoformat(),
        "total_amount": offer["total_amount"],
        "total_currency": offer["total_currency"],
        "expires_at": offer.get("expires_at"),
        "passenger_id": offer["passengers"][0]["id"],
    }


async def search(origin: str, destination: str, day: str) -> list[dict]:
    """One adult, economy, one way. `day` is YYYY-MM-DD in the origin's local date."""
    body = {
        "data": {
            "slices": [{"origin": origin, "destination": destination, "departure_date": day}],
            "passengers": [{"type": "adult"}],
            "cabin_class": "economy",
        }
    }
    data = await _request(
        "POST", "/air/offer_requests", params={"return_offers": "true", "supplier_timeout": 20000}, json=body
    )
    return data.get("offers", [])


async def find_offer_for(option: TravelOption) -> tuple[dict, bool]:
    """Find the Duffel offer for an option. Returns (offer, is_substitute).

    Matches the same flight numbers first. Test mode only sells Duffel Airways, so
    there it falls back to the closest Duffel Airways flight on the same route and
    date (same number of stops, nearest arrival), and says so.
    """
    origin, dest = option.airports[0], option.airports[-1]
    tz = ZoneInfo(_tz_name(origin))
    day = option.legs[0].depart.astimezone(tz).strftime("%Y-%m-%d")
    offers = await search(origin, dest, day)
    if not offers:
        raise DuffelError(f"No bookable offers from {origin} to {dest} on {day}")

    wanted = [leg.flight_no for leg in option.legs]
    for offer in offers:
        if flight_numbers(offer) == wanted:
            return offer, False
    if not is_test():
        raise DuffelError("This exact flight is not bookable through Duffel right now")

    stops = len(option.legs)

    def closeness(o: dict) -> tuple:
        s = summarize(o)
        gap = abs(datetime.fromisoformat(s["arrives"]) - option.arrive)
        return (len(o["slices"][0]["segments"]) != stops, gap > timedelta(hours=6), float(o["total_amount"]))

    return min(offers, key=closeness), True


async def latest(offer_id: str) -> dict:
    """Re-fetch an offer for its current price and availability before charging."""
    return await _request("GET", f"/air/offers/{offer_id}")


async def create_order(offer: dict, passenger: dict) -> dict:
    """Instant order paid from the Duffel balance (after Stripe has charged the traveller)."""
    pax = {
        "id": offer["passengers"][0]["id"],
        "title": passenger["title"],
        "gender": passenger["gender"],
        "given_name": passenger["given_name"],
        "family_name": passenger["family_name"],
        "born_on": passenger["born_on"],
        "email": passenger["email"],
        "phone_number": passenger["phone_number"],
    }
    body = {
        "data": {
            "type": "instant",
            "selected_offers": [offer["id"]],
            "passengers": [pax],
            "payments": [
                {"type": "balance", "currency": offer["total_currency"], "amount": offer["total_amount"]}
            ],
        }
    }
    return await _request("POST", "/air/orders", json=body)


def _tz_name(code: str) -> str:
    from guardian.airports import AIRPORTS

    if code not in AIRPORTS:
        raise DuffelError(f"Unknown airport {code}")
    return AIRPORTS[code][2]


PHONE = re.compile(r"^\+[1-9]\d{6,14}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TITLES = {"mr", "ms", "mrs", "miss", "dr"}


def validate_passenger(p: dict) -> dict:
    """Check the fields Duffel requires; returns a cleaned copy or raises ValueError."""
    clean = {k: str(p.get(k, "")).strip() for k in (
        "title", "gender", "given_name", "family_name", "born_on", "email", "phone_number")}
    clean["title"] = clean["title"].lower()
    clean["gender"] = clean["gender"].lower()[:1]
    problems = []
    if clean["title"] not in TITLES:
        problems.append("title")
    if clean["gender"] not in {"m", "f"}:
        problems.append("gender")
    if not clean["given_name"] or not clean["family_name"]:
        problems.append("name")
    if not DATE.match(clean["born_on"]):
        problems.append("date of birth (YYYY-MM-DD)")
    if "@" not in clean["email"]:
        problems.append("email")
    clean["phone_number"] = re.sub(r"[\s\-()]", "", clean["phone_number"])
    if not PHONE.match(clean["phone_number"]):
        problems.append("phone (international format, e.g. +13135550123)")
    if problems:
        raise ValueError("Please check: " + ", ".join(problems))
    return clean
