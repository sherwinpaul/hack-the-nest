from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Commitment(BaseModel):
    """The thing the user must not miss. The agent protects this, not the flight."""

    title: str
    city: str
    airport: str  # nearest destination airport (IATA)
    must_arrive_by: datetime  # latest airport arrival that still makes the meeting
    meeting_value_usd: float = Field(description="What missing it would cost the user")
    max_extra_spend_usd: float = 1000
    video_fallback_ok: bool = True


class Leg(BaseModel):
    origin: str
    destination: str
    depart: datetime
    arrive: datetime
    carrier: str
    flight_no: str = ""


class TravelOption(BaseModel):
    id: str
    mode: Literal["flight", "flight+ground", "ground"] = "flight"
    legs: list[Leg]
    price_usd: float
    source: str  # kiwi | duffel | google_flights | fixture
    booking_ref: str = ""  # Duffel offer id or deep link

    @property
    def airports(self) -> list[str]:
        return [self.legs[0].origin] + [leg.destination for leg in self.legs]

    @property
    def arrive(self) -> datetime:
        return self.legs[-1].arrive


class AirportRisk(BaseModel):
    airport: str
    disruption_prob: float = Field(ge=0, le=1)
    reason: str


class Evidence(BaseModel):
    title: str
    url: str
    snippet: str = ""


class ScoredOption(BaseModel):
    option: TravelOption
    p_on_time: float
    expected_loss_usd: float  # (1 - p) * meeting_value + price
    extra_cost_usd: float
    explanation: str = ""
