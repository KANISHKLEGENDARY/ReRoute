"""
Autonomous Concierge Agent Tools.

Deterministic, unit-testable tool implementations:
1. `search_alternatives`: queries sandboxed flight inventory for candidates
2. `evaluate_policy_wrapper`: runs policy engine over candidate list
3. `execute_rebooking`: creates sandboxed rebooking confirmation with fake PNR
4. `adjust_hotel`: adjusts check-in dates / late-arrival notes for partner hotel
5. `format_notification`: formats and verifies structured email notification
"""

from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional
import hashlib
from pydantic import BaseModel, Field, ValidationError
from app.schemas.pipeline import (
    CabinClass,
    CandidateFlight,
    HotelOption,
    NotificationPayload,
    OriginalBooking,
    PolicyResult,
    PolicyVerdict,
    TripConstraints,
)
from app.policy.engine import evaluate_policy
from app.sandbox.inventory import FlightInventorySandbox, default_inventory


class SearchAlternativesArgs(BaseModel):
    origin: str = Field(min_length=3, max_length=4, description="Origin 3-letter IATA code, e.g. DEL")
    destination: str = Field(min_length=3, max_length=4, description="Destination 3-letter IATA code, e.g. BOM")
    date_window_days: int = Field(default=1, ge=1, le=5, description="Search date window in days (1-5)")
    allow_alternate_airports: bool = Field(default=False, description="Whether to include alternate city airports")
    allow_connections: bool = Field(default=False, description="Whether to allow connecting flights")


class CheckHotelOptionsArgs(BaseModel):
    city_or_airport: str = Field(min_length=3, max_length=30, description="City name or airport code, e.g. BOM, DEL, GOI")
    checkin_date: str = Field(description="Check-in date in YYYY-MM-DD format")
    checkout_date: str = Field(description="Check-out date in YYYY-MM-DD format")


class CheckPolicyArgs(BaseModel):
    flight_id: str = Field(min_length=5, description="Candidate flight ID to test against policy")


class ProposeFlightChoiceArgs(BaseModel):
    flight_id: str = Field(description="Proposed replacement flight ID")
    rationale: str = Field(description="Explanation of choice considering policy and traveler preferences")


def search_alternatives_tool(
    origin: str,
    destination: str,
    target_date: date,
    cabin_class: CabinClass,
    earliest_departure_time: Optional[datetime] = None,
    inventory: Optional[FlightInventorySandbox] = None,
    max_days_window: int = 1,
) -> List[CandidateFlight]:
    """
    Search candidate flights in the sandboxed inventory across the date window.
    """
    inv = inventory or default_inventory
    results: List[CandidateFlight] = []
    for d in range(max(1, max_days_window)):
        cur_date = target_date + timedelta(days=d)
        day_flights = inv.search_flights(
            origin=origin,
            destination=destination,
            target_date=cur_date,
            cabin_class=cabin_class,
            min_departure_time=earliest_departure_time,
        )
        results.extend(day_flights)
    return results



def evaluate_candidates_tool(
    candidates: List[CandidateFlight],
    original_booking: OriginalBooking,
    constraints: Optional[TripConstraints] = None,
    disruption_time: Optional[datetime] = None,
) -> List[PolicyResult]:
    """
    Evaluates policy for all candidate flights deterministically.
    """
    results: List[PolicyResult] = []
    for cand in candidates:
        res = evaluate_policy(
            candidate=cand,
            original_booking=original_booking,
            constraints=constraints,
            disruption_time=disruption_time,
        )
        results.append(res)
    return results


def execute_rebooking_tool(
    candidate: CandidateFlight,
    original_booking: OriginalBooking,
) -> Dict[str, Any]:
    """
    Executes sandboxed flight rebooking.
    Generates a deterministic synthetic PNR and confirmation reference.
    Charges nothing, modifies test state only.
    """
    seed_str = f"{candidate.flight_id}-{original_booking.pnr}-{original_booking.user_id}"
    hash_digest = hashlib.md5(seed_str.encode("utf-8")).hexdigest()[:6].upper()
    new_pnr = f"RR-{candidate.airline_code}-{hash_digest}"
    new_eticket = f"098-{hash_digest}001"

    fare_delta = round(candidate.fare_inr - original_booking.fare_paid_inr, 2)

    return {
        "status": "CONFIRMED",
        "new_pnr": new_pnr,
        "new_eticket_number": new_eticket,
        "flight_id": candidate.flight_id,
        "flight_number": candidate.flight_number,
        "airline_name": candidate.airline_name,
        "airline_code": candidate.airline_code,
        "origin": candidate.origin,
        "destination": candidate.destination,
        "departure_time": candidate.departure_time.isoformat(),
        "arrival_time": candidate.arrival_time.isoformat(),
        "cabin_class": candidate.cabin_class.value,
        "fare_paid_inr": candidate.fare_inr,
        "fare_delta_inr": fare_delta,
        "rebooked_at": datetime.utcnow().isoformat(),
    }


def adjust_hotel_tool(
    hotel_booking: Optional[HotelOption],
    new_arrival_time: datetime,
    original_arrival_time: datetime,
) -> Optional[Dict[str, Any]]:
    """
    Adjusts linked hotel booking if the new arrival crosses midnight or arrives late.
    """
    if not hotel_booking:
        return None

    new_arrival_date = new_arrival_time.date()
    original_arrival_date = original_arrival_time.date()

    date_shift_days = (new_arrival_date - original_arrival_date).days
    new_checkin = hotel_booking.checkin_date + timedelta(days=date_shift_days)
    new_checkout = hotel_booking.checkout_date + timedelta(days=date_shift_days)

    is_late_checkin = new_arrival_time.hour >= 22 or new_arrival_time.hour < 6

    notes = []
    if date_shift_days > 0:
        notes.append(f"Check-in shifted by {date_shift_days} day(s) due to delayed flight arrival.")
    if is_late_checkin:
        notes.append(f"Late check-in note flagged for arrival at {new_arrival_time.strftime('%H:%M')}.")
    if not notes:
        notes.append("Hotel reservation confirmed with no date shift required.")

    return {
        "hotel_id": hotel_booking.hotel_id,
        "hotel_name": hotel_booking.hotel_name,
        "confirmation_reference": hotel_booking.confirmation_reference,
        "original_checkin": hotel_booking.checkin_date.isoformat(),
        "new_checkin": new_checkin.isoformat(),
        "original_checkout": hotel_booking.checkout_date.isoformat(),
        "new_checkout": new_checkout.isoformat(),
        "date_shift_days": date_shift_days,
        "is_late_checkin": is_late_checkin,
        "status": "MODIFIED" if date_shift_days != 0 else "CONFIRMED",
        "notes": " ".join(notes),
    }


def format_notification_tool(
    original_booking: OriginalBooking,
    disruption_type: str,
    action_type: str,
    new_flight: Optional[Dict[str, Any]],
    hotel_adjustment: Optional[Dict[str, Any]],
    explanation: str,
) -> NotificationPayload:
    """
    Builds the structured notification payload and verifies facts against source data.
    """
    email = original_booking.user_email
    orig_fl = original_booking.flight_number

    if action_type in ["REBOOKED", "REBOOKED_AND_HOTEL"] and new_flight:
        subject = f"Disruption Resolved: You are rebooked on {new_flight['flight_number']} ({original_booking.origin} -> {original_booking.destination})"
        body = (
            f"Dear {original_booking.user_name},\n\n"
            f"Your scheduled flight {orig_fl} encountered a disruption ({disruption_type}).\n\n"
            f"ReRoute has autonomously rebooked you onto:\n"
            f"• Flight: {new_flight['airline_name']} {new_flight['flight_number']}\n"
            f"• New PNR: {new_flight['new_pnr']}\n"
            f"• Departure: {new_flight['departure_time']}\n"
            f"• Arrival: {new_flight['arrival_time']}\n"
            f"• Fare Difference: INR {new_flight['fare_delta_inr']:+.2f}\n\n"
        )
        if hotel_adjustment:
            body += (
                f"Hotel Update ({hotel_adjustment['hotel_name']}):\n"
                f"• Check-in Date: {hotel_adjustment['new_checkin']}\n"
                f"• Notes: {hotel_adjustment['notes']}\n\n"
            )
        body += (
            f"Reasoning:\n{explanation}\n\n"
            f"If you wish to modify or revert this change, visit your ReRoute dashboard.\n"
        )
    elif action_type == "ESCALATED":
        subject = f"Urgent: Action Required for your flight {orig_fl}"
        body = (
            f"Dear {original_booking.user_name},\n\n"
            f"Your scheduled flight {orig_fl} encountered a disruption ({disruption_type}).\n\n"
            f"Our autonomous concierge could not find a compliant alternative within your policy parameters:\n"
            f"{explanation}\n\n"
            f"Your case has been escalated to our priority human support team. Please check your dashboard for manual options.\n"
        )
    else:
        subject = f"Flight Status Update: {orig_fl}"
        body = (
            f"Dear {original_booking.user_name},\n\n"
            f"Your flight {orig_fl} status was checked. No rebooking action was required.\n"
        )

    # Fact verification check
    facts_verified = True
    if new_flight and new_flight["flight_number"] not in body:
        facts_verified = False

    return NotificationPayload(
        subject=subject,
        body=body,
        recipient_email=email,
        facts_verified=facts_verified,
    )
