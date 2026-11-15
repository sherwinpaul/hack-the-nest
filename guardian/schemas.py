from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field

Priority = Literal["price", "balanced", "reliability"]


class Commitment(BaseModel):
    """The event the traveller needs to reach: a wedding, interview, meeting, concert..."""

    title: str
    city: str
    airport: str  # nearest destination airport (IATA)
    must_arrive_by: datetime  # latest airport arrival that still gets them there in time
    priority: Priority = "balanced"  # the traveller's default trade-off; the UI can change it
    remote_fallback_ok: bool = False  # can they join remotely if late (e.g. a video call)?


class Leg(BaseModel):
    origin: str
    destination: str
    depart: datetime
    arrive: datetime
    carrier: str
    flight_no: str = ""
    carrier_name: str = ""


class TravelOption(BaseModel):
    id: str
    mode: Literal["flight", "flight+ground", "ground"] = "flight"
    legs: list[Leg]
    price_usd: float
    source: str  # kiwi | duffel | google_flights | fixture
    booking_ref: str = ""  # Duffel offer id or deep link

    @computed_field
    @property
    def airports(self) -> list[str]:
        return [self.legs[0].origin] + [leg.destination for leg in self.legs]

    @computed_field
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
    score_usd: float  # risk-adjusted cost: price + (1 - p) * priority weight; lower is better
    extra_cost_usd: float  # versus the current booking
    tags: list[str] = []  # recommended | cheapest | most_reliable | booked | too_late
