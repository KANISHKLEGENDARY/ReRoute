"""
Deterministic Policy Engine for ReRoute Travel-Disruption Concierge.

Pure, deterministic rule validation for replacement flights.
No LLM free-text reasoning or unseeded randomness.

Enforces:
1. Seat availability (seats > 0)
2. Route integrity (origin & destination match required endpoints)
3. Cabin class parity (matches original or permitted upgrade)
4. Fare delta ceiling (new fare - original fare <= max threshold)
5. Arrival delay ceiling (candidate arrival - original arrival <= max delay window)
6. Departure feasibility (candidate departure >= disruption/current time + airport buffer)
7. Downstream leg feasibility (candidate arrival + connection buffer <= downstream departure)
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from app.schemas.pipeline import (
    CandidateFlight,
    OriginalBooking,
    PolicyResult,
    PolicyVerdict,
    ReasonCode,
    TripConstraints,
    to_naive_utc,
)

# Equivalent/alternate city airport clusters (if any)
ALLOWED_CITY_ALTERNATES: Dict[str, List[str]] = {
    "DEL": ["DEL"],
    "BOM": ["BOM"],
    "BLR": ["BLR"],
    "HYD": ["HYD"],
    "MAA": ["MAA"],
    "CCU": ["CCU"],
    "AMD": ["AMD"],
    "PNQ": ["PNQ"],
    "GOI": ["GOI"],
}


def evaluate_policy(
    candidate: CandidateFlight,
    original_booking: OriginalBooking,
    constraints: Optional[TripConstraints] = None,
    disruption_time: Optional[datetime] = None,
) -> PolicyResult:
    """
    Pure deterministic policy evaluation.
    Returns PolicyResult with verdict (APPROVED | REJECTED | ESCALATE) and ALL failing reason codes.
    """
    reasons: List[str] = []
    
    # 1. Seat availability check
    if candidate.available_seats <= 0:
        reasons.append(ReasonCode.NO_SEATS_AVAILABLE.value)

    # 2. Route integrity check
    orig_origin = original_booking.origin.upper()
    orig_dest = original_booking.destination.upper()
    cand_origin = candidate.origin.upper()
    cand_dest = candidate.destination.upper()

    allowed_origins = ALLOWED_CITY_ALTERNATES.get(orig_origin, [orig_origin])
    allowed_dests = ALLOWED_CITY_ALTERNATES.get(orig_dest, [orig_dest])

    if cand_origin not in allowed_origins or cand_dest not in allowed_dests:
        reasons.append(ReasonCode.ROUTE_MISMATCH.value)

    # 3. Cabin class check
    allowed_cabins = (
        constraints.allowed_cabins
        if constraints and constraints.allowed_cabins
        else [original_booking.cabin_class]
    )
    if candidate.cabin_class not in allowed_cabins:
        reasons.append(ReasonCode.CABIN_MISMATCH.value)

    # 4. Fare delta calculation & check
    fare_delta = round(candidate.fare_inr - original_booking.fare_paid_inr, 2)
    max_fare_delta = (
        constraints.max_fare_delta_inr if constraints else 5000.0
    )
    if fare_delta > max_fare_delta:
        reasons.append(ReasonCode.FARE_DELTA_EXCEEDED.value)

    # 5. Arrival delay calculation & check
    original_arrival = to_naive_utc(
        constraints.original_arrival_time
        if constraints
        else original_booking.arrival_time
    )
    cand_arrival = to_naive_utc(candidate.arrival_time)
    arrival_diff_seconds = (cand_arrival - original_arrival).total_seconds()
    arrival_delay_minutes = max(0.0, arrival_diff_seconds / 60.0)
    max_delay_hours = constraints.max_delay_hours if constraints else 3.0
    max_delay_minutes = max_delay_hours * 60.0

    if arrival_delay_minutes > max_delay_minutes:
        reasons.append(ReasonCode.ARRIVAL_DELAY_EXCEEDED.value)

    # 6. Departure feasibility check (departure after disruption + airport buffer)
    disruption_time_naive = to_naive_utc(disruption_time)
    if disruption_time_naive is not None:
        buffer_mins = constraints.min_airport_buffer_minutes if constraints else 45
        earliest_allowed_dep = disruption_time_naive + timedelta(minutes=buffer_mins)
        cand_departure = to_naive_utc(candidate.departure_time)
        if cand_departure < earliest_allowed_dep:
            reasons.append(ReasonCode.DEPARTURE_TOO_EARLY.value)

    # 7. Downstream leg connection feasibility check
    downstream_dep = None
    if constraints and constraints.downstream_departure_time:
        downstream_dep = to_naive_utc(constraints.downstream_departure_time)
    elif original_booking.downstream_legs and len(original_booking.downstream_legs) > 0:
        first_downstream = original_booking.downstream_legs[0]
        if "departure_time" in first_downstream:
            dep_val = first_downstream["departure_time"]
            if isinstance(dep_val, str):
                downstream_dep = to_naive_utc(datetime.fromisoformat(dep_val))
            elif isinstance(dep_val, datetime):
                downstream_dep = to_naive_utc(dep_val)

    if downstream_dep is not None:
        conn_buffer_mins = (
            constraints.min_connection_buffer_minutes if constraints else 45
        )
        min_connection_time = cand_arrival + timedelta(minutes=conn_buffer_mins)
        if min_connection_time > downstream_dep:
            reasons.append(ReasonCode.DOWNSTREAM_INFEASIBLE.value)

    # 8. Upstream leg connection feasibility check (replacement departure >= preceding leg arrival + MCT)
    upstream_arr = None
    if constraints and getattr(constraints, "upstream_arrival_time", None):
        upstream_arr = to_naive_utc(constraints.upstream_arrival_time)
    elif getattr(original_booking, "upstream_legs", None) and len(original_booking.upstream_legs) > 0:
        last_upstream = original_booking.upstream_legs[-1]
        if "arrival_time" in last_upstream:
            arr_val = last_upstream["arrival_time"]
            if isinstance(arr_val, str):
                upstream_arr = to_naive_utc(datetime.fromisoformat(arr_val))
            elif isinstance(arr_val, datetime):
                upstream_arr = to_naive_utc(arr_val)

    if upstream_arr is not None:
        conn_buffer_mins = (
            constraints.min_connection_buffer_minutes if constraints else 45
        )
        cand_departure = to_naive_utc(candidate.departure_time)
        earliest_allowed_dep = upstream_arr + timedelta(minutes=conn_buffer_mins)
        if cand_departure < earliest_allowed_dep:
            reasons.append(ReasonCode.UPSTREAM_INFEASIBLE.value)

    # Verdict determination
    if len(reasons) == 0:
        verdict = PolicyVerdict.APPROVED
        reasons_out = [ReasonCode.POLICY_COMPLIANT.value]
    else:
        verdict = PolicyVerdict.REJECTED
        reasons_out = reasons

    return PolicyResult(
        candidate_id=candidate.flight_id,
        verdict=verdict,
        reasons=reasons_out,
        fare_delta_inr=fare_delta,
        arrival_delay_minutes=arrival_delay_minutes,
        details={
            "candidate_flight_number": candidate.flight_number,
            "candidate_departure": candidate.departure_time.isoformat(),
            "candidate_arrival": candidate.arrival_time.isoformat(),
            "candidate_fare": candidate.fare_inr,
            "original_fare": original_booking.fare_paid_inr,
            "max_fare_delta": max_fare_delta,
            "max_delay_hours": max_delay_hours,
        },
    )
