"""
Disruption Event Consumer and State Persister.

Consumes disruption events from the Redis event channel, hydrates booking state
from PostgreSQL, invokes `handle_disruption`, persists stage traces and rebooking
records to the database, and broadcasts updates over WebSockets.
"""

from datetime import datetime, date
import logging
from typing import Any, Dict, Optional
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import async_session_factory
from app.core.activity_feed import activity_feed
from app.models.itinerary import Itinerary
from app.models.flight_leg import FlightLeg
from app.models.hotel import HotelBooking
from app.models.user import User
from app.models.trace import DecisionTrace
from app.schemas.pipeline import (
    ActionType,
    CabinClass,
    DisruptionEvent,
    DisruptionType,
    HotelOption,
    OriginalBooking,
    to_naive_utc,
)
from app.services.trace_sink import DatabaseTraceSink
from app.agent.orchestrator import PipelineDeps
from app.agent.pipeline import handle_disruption
from app.agent.llm import get_llm_client
from app.sandbox.inventory import default_inventory

logger = logging.getLogger("reroute.consumer")


async def process_disruption_event(event_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Main consumer entrypoint for disruption messages.
    Builds state from DB, runs pipeline, persists decision traces and booking changes.
    """
    event_type_str = event_data.get("event_type", "CANCELLED")
    flight_id = event_data.get("flight_id")
    event_id = event_data.get("event_id", f"EVT-{int(datetime.utcnow().timestamp())}")

    logger.info("[CONSUMER] Processing disruption event %s for flight_id %s", event_id, flight_id)

    async with async_session_factory() as session:
        # Check event idempotency: duplicate event_id must not re-run pipeline or duplicate traces
        stmt_check = select(DecisionTrace).where(DecisionTrace.event_id == event_id)
        existing_trace = (await session.execute(stmt_check)).scalars().first()
        if existing_trace:
            logger.info("[CONSUMER] Event %s already processed (idempotency guard). Skipping.", event_id)
            return None

        itinerary = None
        try:
            # 1. Hydrate state from Database
            stmt = (
                select(FlightLeg)
                .options(
                    selectinload(FlightLeg.itinerary).selectinload(Itinerary.user),
                    selectinload(FlightLeg.itinerary).selectinload(Itinerary.hotel_bookings),
                    selectinload(FlightLeg.itinerary).selectinload(Itinerary.flight_legs),
                )
            )
            if flight_id is not None:
                stmt = stmt.where(FlightLeg.id == flight_id)
            else:
                flight_number = event_data.get("flight_number")
                if flight_number:
                    num_clean = flight_number.split("-")[-1]
                    stmt = stmt.where(FlightLeg.flight_number == num_clean)
                else:
                    logger.warning("[CONSUMER] Disruption event missing both flight_id and flight_number.")
                    return None

            result = await session.execute(stmt)
            flight_leg = result.scalars().first()

            if not flight_leg:
                logger.warning("[CONSUMER] No matching FlightLeg found in database for event %s", event_id)
                return None

            itinerary = flight_leg.itinerary
            user = itinerary.user

            # Convert downstream connecting legs (normalized to naive UTC)
            downstream_legs = []
            for other_leg in itinerary.flight_legs:
                if other_leg.id != flight_leg.id and other_leg.leg_order > flight_leg.leg_order:
                    downstream_legs.append({
                        "flight_leg_id": other_leg.id,
                        "flight_number": f"{other_leg.airline_code}-{other_leg.flight_number}",
                        "origin": other_leg.origin,
                        "destination": other_leg.destination,
                        "departure_time": to_naive_utc(other_leg.departure_datetime).isoformat() if other_leg.departure_datetime else "",
                    })

            # Check linked hotel
            hotel_option = None
            if itinerary.hotel_bookings:
                h = itinerary.hotel_bookings[0]
                hotel_option = HotelOption(
                    hotel_id=f"HTL-{h.id}",
                    hotel_name=h.hotel_name,
                    city=flight_leg.destination,
                    airport_code=flight_leg.destination,
                    checkin_date=h.checkin_date,
                    checkout_date=h.checkout_date,
                    room_type="Standard Room",
                    rate_per_night_inr=h.room_rate,
                    status=h.status,
                    confirmation_reference=h.confirmation_reference,
                )

            # Map cabin class
            cabin_enum = CabinClass.ECONOMY
            if flight_leg.cabin_class.upper() == "BUSINESS":
                cabin_enum = CabinClass.BUSINESS
            elif "PREMIUM" in flight_leg.cabin_class.upper():
                cabin_enum = CabinClass.PREMIUM_ECONOMY

            booking_state = OriginalBooking(
                user_id=user.id,
                user_email=user.email,
                user_name=user.name,
                itinerary_id=itinerary.id,
                flight_leg_id=flight_leg.id,
                airline_code=flight_leg.airline_code,
                flight_number=f"{flight_leg.airline_code}-{flight_leg.flight_number}",
                pnr=flight_leg.pnr,
                origin=flight_leg.origin,
                destination=flight_leg.destination,
                departure_time=to_naive_utc(flight_leg.departure_datetime),
                arrival_time=to_naive_utc(flight_leg.arrival_datetime or flight_leg.departure_datetime),
                cabin_class=cabin_enum,
                fare_paid_inr=flight_leg.fare_paid,
                status=flight_leg.status,
                hotel=hotel_option,
                downstream_legs=downstream_legs,
            )

            disruption_event = DisruptionEvent(
                event_id=event_id,
                event_type=DisruptionType(event_type_str) if event_type_str in DisruptionType.__members__ else DisruptionType.CANCELLED,
                flight_id=flight_leg.id,
                flight_number=f"{flight_leg.airline_code}-{flight_leg.flight_number}",
                delay_minutes=event_data.get("delay_minutes", 0),
                reason=event_data.get("reason"),
                notice_text=event_data.get("notice_text"),
                traveler_preferences=event_data.get("traveler_preferences"),
                timestamp=to_naive_utc(datetime.utcnow()),
            )

            # 2. Build Pipeline Deps with DB Trace Sink
            trace_sink = DatabaseTraceSink(session, itinerary.id, event_id=event_id)
            deps = PipelineDeps(
                inventory=default_inventory,
                llm=get_llm_client(),
                trace_sink=trace_sink,
                clock=to_naive_utc(datetime.utcnow()),
            )

            # 3. Execute Pure Pipeline
            decision_result = await handle_disruption(
                event=disruption_event,
                booking=booking_state,
                deps=deps,
            )

            # 4. Flush stage traces to DB
            await trace_sink.flush_to_db()

            # 5. Persist DB mutations according to pipeline action
            if decision_result.action in [ActionType.REBOOKED, ActionType.REBOOKED_AND_HOTEL]:
                flight_leg.status = "DISRUPTED"
                itinerary.status = "REBOOKED"

                new_fl = decision_result.new_flight
                if new_fl:
                    # Insert new rebooked flight segment
                    new_flight_leg = FlightLeg(
                        itinerary_id=itinerary.id,
                        leg_order=flight_leg.leg_order,
                        airline_code=new_fl.get("airline_code", "6E"),
                        flight_number=new_fl.get("flight_number", "").split("-")[-1],
                        pnr=new_fl.get("new_pnr", "RR-REBOOKED"),
                        eticket_number=new_fl.get("new_eticket_number"),
                        origin=new_fl.get("origin", flight_leg.origin),
                        destination=new_fl.get("destination", flight_leg.destination),
                        departure_datetime=datetime.fromisoformat(new_fl["departure_time"]),
                        arrival_datetime=datetime.fromisoformat(new_fl["arrival_time"]),
                        cabin_class=new_fl.get("cabin_class", "ECONOMY"),
                        fare_paid=new_fl.get("fare_paid_inr", flight_leg.fare_paid),
                        currency="INR",
                        status="REBOOKED",
                    )
                    session.add(new_flight_leg)

                # Update hotel if adjusted
                if decision_result.hotel and itinerary.hotel_bookings:
                    htl = itinerary.hotel_bookings[0]
                    htl.checkin_date = date.fromisoformat(decision_result.hotel["new_checkin"])
                    htl.checkout_date = date.fromisoformat(decision_result.hotel["new_checkout"])
                    htl.status = "ADJUSTED"

            elif decision_result.action == ActionType.ESCALATED:
                flight_leg.status = "DISRUPTED"
                itinerary.status = "ESCALATED"
            elif decision_result.action == ActionType.ERROR:
                flight_leg.status = "DISRUPTED"
                itinerary.status = "ERROR"

            await session.commit()

            # 6. Broadcast final action to WebSocket activity stream
            await activity_feed.broadcast(
                "DISRUPTION_RESOLVED",
                {
                    "event_id": event_id,
                    "itinerary_id": itinerary.id,
                    "action": decision_result.action.value,
                    "policy_verdict": decision_result.policy_verdict.value,
                    "fare_delta_inr": decision_result.fare_delta,
                    "explanation": decision_result.explanation,
                    "new_flight": decision_result.new_flight,
                },
            )

            logger.info(
                "[CONSUMER] Disruption processed for itinerary %d: action=%s",
                itinerary.id,
                decision_result.action.value,
            )
            return decision_result.model_dump(mode="json")

        except Exception as e:
            await session.rollback()
            logger.error("[CONSUMER ERROR] Failed to process disruption event %s: %s", event_id, str(e), exc_info=True)
            # Ensure no silent failure: persist emergency RESULT row
            try:
                itin_id = itinerary.id if itinerary else 0
                err_trace = DecisionTrace(
                    event_id=event_id,
                    itinerary_id=itin_id,
                    stage="RESULT",
                    input_snapshot={"event_id": event_id},
                    output_snapshot={
                        "event_id": event_id,
                        "action": "ERROR",
                        "policy_verdict": "ESCALATE",
                        "new_flight": None,
                        "fare_delta_inr": 0.0,
                        "llm_fallback": True,
                        "llm_fallback_reason": "outage",
                        "agent_steps": 0,
                        "revisions_used": 0,
                        "tool_calls": 0,
                        "first_proposal_valid": False,
                        "tokens_in": 0,
                        "tokens_out": 0,
                        "cost_usd": 0.0,
                        "cost_inr": 0.0,
                        "latency_ms": 0.0,
                        "error": str(e),
                    },
                )
                async with async_session_factory() as err_sess:
                    err_sess.add(err_trace)
                    await err_sess.commit()
            except Exception as inner_e:
                logger.error("[CONSUMER ERROR] Could not persist emergency RESULT trace: %s", str(inner_e))
            return None
