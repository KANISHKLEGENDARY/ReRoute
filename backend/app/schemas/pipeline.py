"""
Domain and Pipeline Pydantic Schemas for ReRoute.

Contains structured definitions for disruption events, flight/hotel inventory,
policy evaluation, decision traces, and the top-level DecisionResult.
"""

from datetime import datetime, date
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DisruptionType(str, Enum):
    CANCELLED = "CANCELLED"
    DELAYED = "DELAYED"
    MISSED_CONNECTION = "MISSED_CONNECTION"
    DIVERTED = "DIVERTED"
    NONE = "NONE"


class PolicyVerdict(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATE = "ESCALATE"


class ActionType(str, Enum):
    REBOOKED = "REBOOKED"
    HOTEL_ONLY = "HOTEL_ONLY"
    REBOOKED_AND_HOTEL = "REBOOKED_AND_HOTEL"
    ESCALATED = "ESCALATED"
    NO_ACTION = "NO_ACTION"
    ERROR = "ERROR"


def to_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Converts timezone-aware or naive datetimes to normalized naive UTC datetimes."""
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        from datetime import timezone
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class ReasonCode(str, Enum):
    POLICY_COMPLIANT = "POLICY_COMPLIANT"
    CABIN_MISMATCH = "CABIN_MISMATCH"
    FARE_DELTA_EXCEEDED = "FARE_DELTA_EXCEEDED"
    ARRIVAL_DELAY_EXCEEDED = "ARRIVAL_DELAY_EXCEEDED"
    DEPARTURE_TOO_EARLY = "DEPARTURE_TOO_EARLY"
    ROUTE_MISMATCH = "ROUTE_MISMATCH"
    DOWNSTREAM_INFEASIBLE = "DOWNSTREAM_INFEASIBLE"
    UPSTREAM_INFEASIBLE = "UPSTREAM_INFEASIBLE"
    NO_SEATS_AVAILABLE = "NO_SEATS_AVAILABLE"
    NO_VALID_CANDIDATE = "NO_VALID_CANDIDATE"
    SOFT_BREACH_DELAY = "SOFT_BREACH_DELAY"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    DISRUPTION_NOT_FOUND = "DISRUPTION_NOT_FOUND"


class CabinClass(str, Enum):
    ECONOMY = "ECONOMY"
    PREMIUM_ECONOMY = "PREMIUM_ECONOMY"
    BUSINESS = "BUSINESS"
    FIRST = "FIRST"


class CandidateFlight(BaseModel):
    flight_id: str
    airline_code: str
    airline_name: str
    flight_number: str
    origin: str
    destination: str
    departure_time: datetime
    arrival_time: datetime
    cabin_class: CabinClass = CabinClass.ECONOMY
    fare_inr: float
    available_seats: int = 9
    aircraft_type: str = "A320neo"
    is_direct: bool = True
    connection_airports: List[str] = Field(default_factory=list)


class HotelOption(BaseModel):
    hotel_id: str
    hotel_name: str
    city: str
    airport_code: str
    checkin_date: date
    checkout_date: date
    room_type: str = "Standard Room"
    rate_per_night_inr: float = 4000.0
    status: str = "CONFIRMED"
    confirmation_reference: str = "HTL-CONF-001"
    address: Optional[str] = None


class TripConstraints(BaseModel):
    max_fare_delta_inr: float = 5000.0
    max_delay_hours: float = 3.0
    min_airport_buffer_minutes: int = 45
    min_connection_buffer_minutes: int = 45
    allowed_cabins: List[CabinClass] = Field(default_factory=lambda: [CabinClass.ECONOMY])
    required_origin: str
    required_destination: str
    earliest_departure_time: datetime
    original_arrival_time: datetime
    downstream_departure_time: Optional[datetime] = None
    upstream_arrival_time: Optional[datetime] = None


class DisruptionEvent(BaseModel):
    event_id: str
    event_type: DisruptionType
    flight_id: Optional[int] = None
    flight_number: Optional[str] = None
    delay_minutes: int = 0
    diverted_to: Optional[str] = None
    reason: Optional[str] = None
    notice_text: Optional[str] = None
    traveler_preferences: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: Dict[str, Any] = Field(default_factory=dict)


class OriginalBooking(BaseModel):
    user_id: int
    user_email: str
    user_name: str
    itinerary_id: int
    flight_leg_id: int
    airline_code: str
    flight_number: str
    pnr: str
    origin: str
    destination: str
    departure_time: datetime
    arrival_time: datetime
    cabin_class: CabinClass = CabinClass.ECONOMY
    fare_paid_inr: float
    status: str = "CONFIRMED"
    hotel: Optional[HotelOption] = None
    downstream_legs: List[Dict[str, Any]] = Field(default_factory=list)
    upstream_legs: List[Dict[str, Any]] = Field(default_factory=list)


class PolicyResult(BaseModel):
    candidate_id: str
    verdict: PolicyVerdict
    reasons: List[str] = Field(default_factory=list)
    fare_delta_inr: float = 0.0
    arrival_delay_minutes: float = 0.0
    details: Dict[str, Any] = Field(default_factory=dict)


class NotificationPayload(BaseModel):
    subject: str
    body: str
    recipient_email: str
    facts_verified: bool = True


class DecisionMetrics(BaseModel):
    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    cost_inr: float = 0.0
    llm_fallback: bool = False



class DecisionResult(BaseModel):
    event_id: str
    detected: bool
    disruption_type: DisruptionType
    alternatives_considered: List[Dict[str, Any]] = Field(default_factory=list)
    policy_verdict: PolicyVerdict
    policy_reasons: List[str] = Field(default_factory=list)
    action: ActionType
    new_flight: Optional[Dict[str, Any]] = None
    hotel: Optional[Dict[str, Any]] = None
    fare_delta: float = 0.0
    explanation: str = ""
    citations: List[str] = Field(default_factory=list)
    notification: Dict[str, str] = Field(default_factory=dict)
    trace_stages: List[Dict[str, Any]] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
