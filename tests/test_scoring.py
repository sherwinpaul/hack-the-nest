from guardian.tools import compute_ranking


def test_storm_scenario_prefers_route_avoiding_ord():
    ranked = compute_ranking()
    assert ranked[0]["option"]["id"] == "alt-F9-nonstop"


def test_late_arrival_scores_zero():
    by_id = {r["option"]["id"]: r for r in compute_ranking()}
    assert by_id["alt-UA-via-ORD-late"]["p_on_time"] == 0.0


def test_current_trip_through_storm_is_risky():
    by_id = {r["option"]["id"]: r for r in compute_ranking()}
    assert by_id["current-UA-via-ORD"]["p_on_time"] < 0.6
