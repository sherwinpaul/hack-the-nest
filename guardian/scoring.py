"""Deterministic ranking. The LLM explains the ranking; it never computes it.

Each option gets a risk-adjusted cost:

    score = price + (1 - P(on time)) * weight

`weight` is how much the traveller would pay to be certain of arriving, and comes
from their priority. A cheapest-first traveller barely pays for reliability; a
must-be-there traveller pays a lot. Options that land after the deadline always
rank last.
"""

from guardian.schemas import (
    AirportRisk,
    Commitment,
    Priority,
    ScoredOption,
    TravelOption,
)

CONNECTION_PENALTY = 0.03  # each extra connection adds some missed-connection risk
SLACK_FULL_CREDIT_MIN = 180  # with 3h+ slack, a short delay no longer matters

# USD the traveller would pay to remove a 100% chance of missing the event.
PRIORITY_WEIGHT_USD: dict[str, float] = {
    "price": 300,
    "balanced": 2000,
    "reliability": 10000,
}


def p_on_time(option: TravelOption, risks: dict[str, AirportRisk], c: Commitment) -> float:
    slack_min = (c.must_arrive_by - option.arrive).total_seconds() / 60
    if slack_min < 0:
        return 0.0

    p = 1.0
    for code in option.airports:
        r = risks.get(code)
        if r:
            # Slack absorbs part of each airport's disruption risk.
            absorb = min(slack_min / SLACK_FULL_CREDIT_MIN, 1.0) * 0.5
            p *= 1 - r.disruption_prob * (1 - absorb)
    p *= (1 - CONNECTION_PENALTY) ** (len(option.legs) - 1)
    return round(p, 3)


def rank(
    options: list[TravelOption],
    risks: list[AirportRisk],
    c: Commitment,
    current_id: str,
    priority: Priority | None = None,
) -> list[ScoredOption]:
    weight = PRIORITY_WEIGHT_USD[priority or c.priority]
    risk_map = {r.airport: r for r in risks}
    baseline = next((o.price_usd for o in options if o.id == current_id), None)
    scored = []
    for o in options:
        p = p_on_time(o, risk_map, c)
        extra = max(o.price_usd - baseline, 0) if baseline is not None else 0
        scored.append(
            ScoredOption(
                option=o,
                p_on_time=p,
                score_usd=round(o.price_usd + (1 - p) * weight, 2),
                extra_cost_usd=round(extra, 2),
            )
        )
    scored.sort(key=lambda s: (s.p_on_time == 0, s.score_usd))
    _tag(scored, current_id)
    return scored


def _tag(scored: list[ScoredOption], current_id: str) -> None:
    viable = [s for s in scored if s.p_on_time > 0]
    if viable:
        viable[0].tags.append("recommended")
        min(viable, key=lambda s: (s.option.price_usd, -s.p_on_time)).tags.append("cheapest")
        max(viable, key=lambda s: (s.p_on_time, -s.option.price_usd)).tags.append("most_reliable")
    for s in scored:
        if s.option.id == current_id:
            s.tags.append("booked")
        if s.p_on_time == 0:
            s.tags.append("too_late")
