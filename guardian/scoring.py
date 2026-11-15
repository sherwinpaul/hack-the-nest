"""Deterministic decision math. The LLM explains the ranking; it never computes it."""

from guardian.schemas import AirportRisk, Commitment, ScoredOption, TravelOption

CONNECTION_PENALTY = 0.03  # each extra connection adds some missed-connection risk
SLACK_FULL_CREDIT_MIN = 180  # with 3h+ slack, a short delay no longer matters


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
    baseline_price: float,
) -> list[ScoredOption]:
    risk_map = {r.airport: r for r in risks}
    scored = []
    for o in options:
        p = p_on_time(o, risk_map, c)
        extra = max(o.price_usd - baseline_price, 0)
        if extra > c.max_extra_spend_usd:
            continue
        scored.append(
            ScoredOption(
                option=o,
                p_on_time=p,
                expected_loss_usd=round((1 - p) * c.meeting_value_usd + o.price_usd, 2),
                extra_cost_usd=round(extra, 2),
            )
        )
    return sorted(scored, key=lambda s: s.expected_loss_usd)
