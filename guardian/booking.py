"""Booking runs only after explicit user approval. Duffel test mode only."""

from guardian.config import settings
from guardian.schemas import TravelOption


def book(option: TravelOption) -> str:
    token = settings().duffel_access_token
    if not token:
        return f"[simulated] Would book {option.id} via {option.source} for ${option.price_usd:.0f}"
    if not token.startswith("duffel_test_"):
        raise RuntimeError("Refusing to book with a non-test Duffel token.")
    # TODO: POST https://api.duffel.com/air/orders with the selected offer id
    # (option.booking_ref) and passenger details collected in the UI.
    return f"[duffel test] order pending for offer {option.booking_ref}"
