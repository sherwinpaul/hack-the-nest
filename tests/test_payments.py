"""Checkout safety rules, with Stripe and Duffel replaced by fakes (no network)."""

import asyncio
from types import SimpleNamespace

import pytest

from guardian import duffel, payments

OFFER = {
    "id": "off_123",
    "total_amount": "212.40",
    "total_currency": "USD",
    "owner": {"name": "Duffel Airways", "iata_code": "ZZ"},
    "passengers": [{"id": "pas_1"}],
    "expires_at": "2026-11-15T12:00:00Z",
    "slices": [{"segments": [{
        "origin": {"iata_code": "DTW", "time_zone": "America/Detroit"},
        "destination": {"iata_code": "DEN", "time_zone": "America/Denver"},
        "departing_at": "2026-11-17T09:00:00", "arriving_at": "2026-11-17T10:35:00",
        "marketing_carrier": {"iata_code": "ZZ"}, "marketing_carrier_flight_number": "1702",
    }]}],
}
PASSENGER = {
    "title": "ms", "gender": "f", "given_name": "Test", "family_name": "Traveller",
    "born_on": "1990-01-01", "email": "test@example.com", "phone_number": "+1 313 555 0123",
}


class FakeStripe:
    def __init__(self, status="succeeded", received=21240, currency="usd"):
        self.refunds_made = []
        intent = SimpleNamespace(id="pi_1", status=status, amount_received=received, currency=currency)
        self.v1 = SimpleNamespace(
            payment_intents=SimpleNamespace(retrieve=lambda _id: intent),
            refunds=SimpleNamespace(create=lambda params: self.refunds_made.append(params)),
        )


@pytest.fixture
def checkout(monkeypatch):
    payments._checkouts.clear()
    co = payments.Checkout(
        id="co_1", option_id="opt", offer=OFFER, substitute=True,
        amount_minor=21240, currency="USD", payment_intent_id="pi_1",
    )
    payments._checkouts["co_1"] = co
    orders = []

    async def latest(_id):
        return OFFER

    async def create_order(offer, pax):
        orders.append(pax)
        return {"id": "ord_1", "booking_reference": "ABC123", "owner": offer["owner"],
                "total_amount": offer["total_amount"], "total_currency": offer["total_currency"]}

    monkeypatch.setattr(duffel, "latest", latest)
    monkeypatch.setattr(duffel, "create_order", create_order)
    monkeypatch.setattr(duffel, "is_test", lambda: True)
    return SimpleNamespace(co=co, orders=orders, monkeypatch=monkeypatch)


def run(coro):
    return asyncio.run(coro)


def use_stripe(ctx, fake):
    ctx.monkeypatch.setattr(payments, "_stripe", lambda: fake)
    return fake


def test_books_after_successful_payment_and_is_idempotent(checkout):
    use_stripe(checkout, FakeStripe())
    first = run(payments.complete_booking("co_1", PASSENGER))
    again = run(payments.complete_booking("co_1", PASSENGER))
    assert first["booking_reference"] == "ABC123" and again is first
    assert len(checkout.orders) == 1  # a double click never books twice
    assert checkout.orders[0]["phone_number"] == "+13135550123"


def test_no_booking_unless_payment_succeeded(checkout):
    fake = use_stripe(checkout, FakeStripe(status="requires_payment_method"))
    with pytest.raises(payments.CheckoutError, match="not completed"):
        run(payments.complete_booking("co_1", PASSENGER))
    assert checkout.orders == [] and fake.refunds_made == []


def test_refunds_when_amount_does_not_match(checkout):
    fake = use_stripe(checkout, FakeStripe(received=100))
    with pytest.raises(payments.CheckoutError, match="refunded"):
        run(payments.complete_booking("co_1", PASSENGER))
    assert checkout.orders == [] and len(fake.refunds_made) == 1


def test_refunds_when_airline_order_fails(checkout):
    fake = use_stripe(checkout, FakeStripe())

    async def failing_order(offer, pax):
        raise duffel.DuffelError("offer no longer available")

    checkout.monkeypatch.setattr(duffel, "create_order", failing_order)
    with pytest.raises(payments.CheckoutError, match="refunded"):
        run(payments.complete_booking("co_1", PASSENGER))
    assert len(fake.refunds_made) == 1


def test_refunds_when_fare_changed_after_payment(checkout):
    fake = use_stripe(checkout, FakeStripe())

    async def pricier(_id):
        return {**OFFER, "total_amount": "250.00"}

    checkout.monkeypatch.setattr(duffel, "latest", pricier)
    with pytest.raises(payments.CheckoutError, match="refunded"):
        run(payments.complete_booking("co_1", PASSENGER))
    assert checkout.orders == [] and len(fake.refunds_made) == 1


def test_invalid_passenger_before_payment_charges_nothing(checkout):
    fake = use_stripe(checkout, FakeStripe(status="requires_payment_method"))
    with pytest.raises(payments.CheckoutError, match="phone"):
        run(payments.complete_booking("co_1", {**PASSENGER, "phone_number": "555"}))
    assert checkout.orders == [] and fake.refunds_made == []


def test_invalid_passenger_after_payment_is_refunded(checkout):
    fake = use_stripe(checkout, FakeStripe())
    with pytest.raises(payments.CheckoutError, match="refunded"):
        run(payments.complete_booking("co_1", {**PASSENGER, "phone_number": "555"}))
    assert checkout.orders == [] and len(fake.refunds_made) == 1


def test_unknown_checkout():
    with pytest.raises(payments.CheckoutError, match="expired"):
        run(payments.complete_booking("nope", PASSENGER))


def test_minor_units():
    assert payments.to_minor("212.40", "USD") == 21240
    assert payments.to_minor("15000", "JPY") == 15000


def test_offer_summary_uses_airport_time_zones():
    s = duffel.summarize(OFFER)
    assert s["flights"] == ["ZZ 1702"] and s["route"] == ["DTW", "DEN"]
    assert s["departs"] == "2026-11-17T14:00:00+00:00"  # 9:00 EST
    assert s["arrives"] == "2026-11-17T17:35:00+00:00"  # 10:35 MST


def test_live_keys_are_refused(monkeypatch):
    from guardian import config

    fake = SimpleNamespace(duffel_access_token="duffel_test_x", stripe_secret_key="sk_live_x",
                           stripe_publishable_key="pk_live_x")
    monkeypatch.setattr(payments, "settings", lambda: fake)
    ok, why = payments.enabled()
    assert not ok and "pk_test_" in why
    assert config  # imported for clarity: settings come from guardian.config
