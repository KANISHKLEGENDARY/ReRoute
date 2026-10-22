"""
Disruption Detection Service.

Evaluates raw incoming event signals and current booking state to identify:
1. Cancellations
2. Excessive delays
3. Broken connections (Missed connections)
4. Diversions
5. Idempotent duplicate events / already rebooked trips
"""

from datetime import datetime, timedelta
from typing import Optional, Tuple
from app.schemas.pipeline import (
    DisruptionEvent,
    DisruptionType,
    OriginalBooking,
    ReasonCode,
)


def detect_disruption(
    event: DisruptionEvent,
    booking: OriginalBooking,
    min_connection_buffer_minutes: int = 45,
) -> Tuple[bool, DisruptionType, Optional[str]]:
    """
    Evaluates whether an incoming event constitutes an actionable disruption.
    
    Returns:
        (is_disrupted: bool, disruption_type: DisruptionType, reason_text: Optional[str])
    """
    # 1. Idempotency Check: if booking is already in a terminal state
    if booking.status.upper() in ["REBOOKED", "CANCELLED_RESOLVED", "COMPLETED"]:
        return False, DisruptionType.NONE, ReasonCode.DUPLICATE_EVENT.value

    event_type = event.event_type

    # 2. Explicit Cancellation
    if event_type == DisruptionType.CANCELLED:
        reason = event.reason or f"Flight {booking.flight_number} cancelled by airline."
        return True, DisruptionType.CANCELLED, reason

    # 3. Diversion
    if event_type == DisruptionType.DIVERTED:
        diverted_to = event.diverted_to or "an alternate airport"
        return True, DisruptionType.DIVERTED, f"Flight diverted to {diverted_to}."

    # 4. Missed Connection / Delay check
    if event_type == DisruptionType.MISSED_CONNECTION:
        return True, DisruptionType.MISSED_CONNECTION, "Connection window broken; incoming flight delayed."

    if event_type == DisruptionType.DELAYED or event.delay_minutes > 0:
        delay = event.delay_minutes
        
        # Check if downstream leg exists and connection would break
        if booking.downstream_legs and len(booking.downstream_legs) > 0:
            first_downstream = booking.downstream_legs[0]
            downstream_dep = first_downstream.get("departure_time")
            if isinstance(downstream_dep, str):
                downstream_dep = datetime.fromisoformat(downstream_dep)
            
            from app.schemas.pipeline import to_naive_utc
            downstream_dep = to_naive_utc(downstream_dep)
            booking_arr = to_naive_utc(booking.arrival_time)
            
            if isinstance(downstream_dep, datetime) and isinstance(booking_arr, datetime):
                new_arrival = booking_arr + timedelta(minutes=delay)
                min_viable_dep = new_arrival + timedelta(minutes=min_connection_buffer_minutes)
                if min_viable_dep > downstream_dep:
                    return (
                        True,
                        DisruptionType.MISSED_CONNECTION,
                        f"Delay of {delay} mins breaks minimum {min_connection_buffer_minutes}m layover for connection {first_downstream.get('flight_number')}.",
                    )

        # Standalone significant delay threshold (> 60 mins is an actionable delay)
        if delay >= 60:
            return True, DisruptionType.DELAYED, f"Flight delayed by {delay} minutes."
        elif delay > 0:
            # Minor delay (< 60m with no broken connection) - monitored, but no rebooking required
            return False, DisruptionType.NONE, f"Minor delay of {delay} mins within acceptable threshold."

    # Default: no actionable disruption detected
    return False, DisruptionType.NONE, "Flight on time; no disruption detected."
