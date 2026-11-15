"""In-app checkout: Stripe collects the traveller's payment, Duffel issues the booking.

Flow (all server-verified, test keys only):
  1. start_checkout(option)  -> find + re-price the Duffel offer, create a Stripe
                                PaymentIntent for exactly that amount
  2. traveller enters passenger details and pays in the Stripe Payment Element
  3. complete_booking(...)   -> confirm the PaymentIntent succeeded for the right
                                amount, re-check the offer price, create the Duffel
                                order; refund automatically if the order fails
"""

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from decimal import Decimal

import stripe

from guardian import duffel
from guardian.config import settings
from guardian.schemas import TravelOption

CHECKOUT_TTL = 20 * 60
ZERO_DECIMAL = {"JPY", "KRW", "VND", "CLP", "ISK", "HUF", "TWD", "UGX", "XAF", "XOF"}


class CheckoutError(RuntimeError):
    pass


@dataclass
class Checkout:
    id: str
    option_id: str
    offer: dict
    substitute: bool
    amount_minor: int
    currency: str
    payment_intent_id: str
    created: float = field(default_factory=time.monotonic)
    booking: dict | None = None


_checkouts: dict[str, Checkout] = {}


def enabled() -> tuple[bool, str]:
    s = settings()
    missing = [
        name
        for name, v in (
            ("DUFFEL_ACCESS_TOKEN", s.duffel_access_token),
            ("STRIPE_SECRET_KEY", s.stripe_secret_key),
            ("STRIPE_PUBLISHABLE_KEY", s.stripe_publishable_key),
        )
        if not v
    ]
    if missing:
        return False, "Add " + ", ".join(missing) + " to .env to enable in-app booking"
    if not s.stripe_publishable_key.startswith("pk_test_"):
        return False, "STRIPE_PUBLISHABLE_KEY must be the test publishable key (pk_test_...)"
    # A restricted key (rk_test_) works too if it can write PaymentIntents and Refunds.
    if not s.stripe_secret_key.startswith(("sk_test_", "rk_test_")):
        return False, "Only Stripe test keys (sk_test_ or rk_test_) are allowed in this prototype"
    if not s.duffel_access_token.startswith("duffel_test_"):
        return False, "Only Duffel test tokens (duffel_test_) are allowed in this prototype"
    return True, ""


def _stripe() -> stripe.StripeClient:
    ok, why = enabled()
    if not ok:
        raise CheckoutError(why)
    return stripe.StripeClient(settings().stripe_secret_key)


def to_minor(amount: str, currency: str) -> int:
    d = Decimal(amount)
    return int(d) if currency.upper() in ZERO_DECIMAL else int((d * 100).quantize(Decimal(1)))


async def start_checkout(option: TravelOption) -> dict:
    client = _stripe()
    try:
        offer, substitute = await duffel.find_offer_for(option)
        offer = await duffel.latest(offer["id"])
    except duffel.DuffelError as e:
        raise CheckoutError(str(e)) from e

    currency = offer["total_currency"].upper()
    amount = to_minor(offer["total_amount"], currency)
    checkout_id = secrets.token_urlsafe(16)
    intent = await asyncio.to_thread(
        client.v1.payment_intents.create,
        params={
            "amount": amount,
            "currency": currency.lower(),
            "automatic_payment_methods": {"enabled": True, "allow_redirects": "never"},
            "description": f"Flight {' / '.join(duffel.flight_numbers(offer))}",
            "metadata": {"checkout_id": checkout_id, "offer_id": offer["id"], "option_id": option.id},
        },
    )
    _gc()
    _checkouts[checkout_id] = Checkout(
        id=checkout_id,
        option_id=option.id,
        offer=offer,
        substitute=substitute,
        amount_minor=amount,
        currency=currency,
        payment_intent_id=intent.id,
    )
    return {
        "checkout_id": checkout_id,
        "client_secret": intent.client_secret,
        "publishable_key": settings().stripe_publishable_key,
        "offer": duffel.summarize(offer),
        "substitute": substitute,
        "test_mode": duffel.is_test(),
    }


async def complete_booking(checkout_id: str, passenger: dict) -> dict:
    co = _checkouts.get(checkout_id)
    if co is None:
        raise CheckoutError("This checkout expired. Please start again.")
    if co.booking:
        return co.booking  # idempotent: a double click never books twice

    client = _stripe()
    intent = await asyncio.to_thread(client.v1.payment_intents.retrieve, co.payment_intent_id)
    try:
        pax = duffel.validate_passenger(passenger)
    except ValueError as e:
        # The dashboard validates before payment; if bad details still arrive after a
        # successful charge, give the money back rather than keep it without a ticket.
        if intent.status == "succeeded":
            await _refund(client, co, "invalid passenger details")
            raise CheckoutError(f"{e}. Your payment has been refunded.") from e
        raise CheckoutError(str(e)) from e
    if intent.status != "succeeded":
        raise CheckoutError(f"Payment not completed (status: {intent.status})")
    if intent.amount_received != co.amount_minor or intent.currency.upper() != co.currency:
        await _refund(client, co, "amount mismatch")
        raise CheckoutError("Payment amount did not match the fare. You have been refunded.")

    try:
        offer = await duffel.latest(co.offer["id"])
        if to_minor(offer["total_amount"], offer["total_currency"]) != co.amount_minor:
            raise duffel.DuffelError("The fare changed after payment")
        order = await duffel.create_order(offer, pax)
    except duffel.DuffelError as e:
        await _refund(client, co, str(e))
        raise CheckoutError(f"The airline could not confirm the booking ({e}). You have been refunded.") from e

    co.booking = {
        "booking_reference": order.get("booking_reference"),
        "order_id": order.get("id"),
        "airline": order.get("owner", {}).get("name"),
        "total": f"{order.get('total_amount')} {order.get('total_currency')}",
        "flights": duffel.flight_numbers(offer),
        "substitute": co.substitute,
        "test_mode": duffel.is_test(),
    }
    return co.booking


async def _refund(client: stripe.StripeClient, co: Checkout, reason: str) -> None:
    await asyncio.to_thread(
        client.v1.refunds.create,
        params={"payment_intent": co.payment_intent_id, "metadata": {"reason": reason[:400]}},
    )


def _gc() -> None:
    now = time.monotonic()
    for k in [k for k, c in _checkouts.items() if now - c.created > CHECKOUT_TTL]:
        _checkouts.pop(k, None)
