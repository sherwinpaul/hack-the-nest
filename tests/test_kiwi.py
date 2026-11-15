from datetime import UTC, datetime

from guardian.airports import tz_for
from guardian.kiwi import parse_itinerary

# Real shape returned by Kiwi's search-flight (DTW -> DFW -> DEN, Frontier).
ITINERARY = {
    "id": "244d0713512600005568af85_0|244d0713512600005568af85_1",
    "price": 192.0,
    "bookingUrl": "https://kiwi.com/u/fbwsux",
    "outbound": {
        "segments": [
            {"from": "DTW", "to": "DFW", "departureTime": "2026-11-17T10:07:00",
             "arrivalTime": "2026-11-17T12:22:00", "durationSeconds": 11700,
             "carrier": "F9", "flightNumber": "F93177"},
            {"from": "DFW", "to": "DEN", "departureTime": "2026-11-17T14:39:00",
             "arrivalTime": "2026-11-17T15:53:00", "durationSeconds": 8040,
             "carrier": "F9", "flightNumber": "F94069"},
        ]
    },
}


def test_converts_local_times_to_utc_across_zones():
    o = parse_itinerary(ITINERARY, tz_for("DTW"))
    # DTW is UTC-5 in November, DFW UTC-6, DEN UTC-7.
    assert o.legs[0].depart == datetime(2026, 11, 17, 15, 7, tzinfo=UTC)
    assert o.legs[0].arrive == datetime(2026, 11, 17, 18, 22, tzinfo=UTC)
    assert o.legs[1].depart == datetime(2026, 11, 17, 20, 39, tzinfo=UTC)
    assert o.arrive == datetime(2026, 11, 17, 22, 53, tzinfo=UTC)  # 15:53 MST


def test_fields():
    o = parse_itinerary(ITINERARY, tz_for("DTW"))
    assert o.airports == ["DTW", "DFW", "DEN"]
    assert [leg.flight_no for leg in o.legs] == ["F9 3177", "F9 4069"]
    assert o.price_usd == 192.0 and o.source == "kiwi"
    assert o.booking_ref == "https://kiwi.com/u/fbwsux"
    assert o.id == parse_itinerary(ITINERARY, tz_for("DTW")).id  # stable across calls


def test_no_segments_returns_none():
    assert parse_itinerary({"id": "x", "price": 1, "outbound": {"segments": []}}, tz_for("DTW")) is None
