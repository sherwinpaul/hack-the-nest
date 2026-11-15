import pytest

from guardian import data
from guardian.tools import compute_ranking


@pytest.fixture(autouse=True)
def reset_priority():
    data._priority = None
    yield
    data._priority = None


def by_id(ranked):
    return {r["option"]["id"]: r for r in ranked}


def test_balanced_prefers_route_avoiding_the_storm():
    ranked = compute_ranking("balanced")
    assert ranked[0]["option"]["id"] == "alt-F9-nonstop"
    assert "recommended" in ranked[0]["tags"]


def test_price_priority_keeps_the_cheap_booking():
    ranked = compute_ranking("price")
    assert ranked[0]["option"]["id"] == "current-UA-via-ORD"
    assert {"recommended", "cheapest", "booked"} <= set(ranked[0]["tags"])


def test_reliability_priority_picks_highest_on_time_chance():
    ranked = compute_ranking("reliability")
    assert ranked[0]["option"]["id"] == "alt-F9-nonstop"
    assert "most_reliable" in ranked[0]["tags"]


def test_late_arrival_ranks_last_and_is_never_cheapest():
    ranked = compute_ranking("price")
    late = by_id(ranked)["alt-UA-via-ORD-late"]
    assert late["p_on_time"] == 0.0
    assert ranked[-1] is late
    assert late["tags"] == ["too_late"]  # cheaper than everything, but not "cheapest"


def test_current_trip_through_storm_is_risky():
    assert by_id(compute_ranking())["current-UA-via-ORD"]["p_on_time"] < 0.6


def test_priority_choice_persists_for_later_rankings():
    data.set_priority("price")
    assert compute_ranking()[0]["option"]["id"] == "current-UA-via-ORD"
    with pytest.raises(ValueError):
        data.set_priority("fastest")
