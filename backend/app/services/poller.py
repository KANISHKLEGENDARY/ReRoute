"""
Background Flight-Status Poller Service.

Runs as a background lifespan task in FastAPI.
Logs EVERY check into the `poll_log` database table (routine ON_TIME or otherwise)
and publishes actionable disruptions onto the Redis event channel.
Broadcasts live heartbeat checks to the WebSocket activity stream.
"""

import asyncio
from datetime import datetime
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.redis import publish_event
from app.core.activity_feed import activity_feed
from app.models.flight_leg import FlightLeg, PollLog

logger = logging.getLogger("reroute.poller")
settings = get_settings()


async def check_single_leg(session: AsyncSession, leg: FlightLeg) -> Optional[dict]:
    """
    Evaluates a single flight leg, records a PollLog entry, and returns disruption payload if disrupted.
    """
    now = datetime.utcnow()
    
    # 1. Write audit log of poll check
    poll_entry = PollLog(
        flight_leg_id=leg.id,
        status=leg.status,
        checked_at=now,
    )
    session.add(poll_entry)

    # 2. Broadcast routine check to WebSocket feed
    await activity_feed.broadcast(
        "POLL_CHECK",
        {
            "flight_leg_id": leg.id,
            "flight_number": f"{leg.airline_code}-{leg.flight_number}",
            "route": f"{leg.origin} -> {leg.destination}",
            "status": leg.status,
            "checked_at": now.isoformat(),
        },
    )

    # 3. If leg status is marked as disrupted, prepare disruption event
    if leg.status in ["CANCELLED", "DELAYED", "MISSED_CONNECTION", "DIVERTED"]:
        return {
            "event_id": f"POLL-EVT-{leg.id}-{int(now.timestamp())}",
            "event_type": leg.status,
            "flight_id": leg.id,
            "flight_number": f"{leg.airline_code}-{leg.flight_number}",
            "delay_minutes": 120 if leg.status == "DELAYED" else 0,
            "reason": f"Status check flagged {leg.status}",
            "timestamp": now.isoformat(),
        }
    return None


async def run_poll_cycle() -> None:
    """
    Performs one complete pass of status checks over all active flight legs.
    """
    async with async_session_factory() as session:
        try:
            # Query all active flight legs
            stmt = select(FlightLeg).where(FlightLeg.status.in_(["ON_TIME", "CANCELLED", "DELAYED", "MISSED_CONNECTION"]))
            result = await session.execute(stmt)
            legs = result.scalars().all()

            disruptions_to_publish = []
            for leg in legs:
                disruption_event = await check_single_leg(session, leg)
                if disruption_event:
                    disruptions_to_publish.append(disruption_event)

            await session.commit()

            # Publish disruptions to Redis channel
            for event in disruptions_to_publish:
                await publish_event(settings.REDIS_CHANNEL, event)
                logger.info("[POLLER] Published disruption event for flight %s", event["flight_number"])

        except Exception as e:
            await session.rollback()
            logger.error("[POLLER ERROR] Error during poll cycle: %s", str(e))


async def start_flight_poller(stop_event: asyncio.Event) -> None:
    """
    Background worker loop that runs continuously until server shutdown.
    """
    logger.info("[POLLER] Background flight-status poller started (interval: %ds).", settings.POLLER_INTERVAL_SECONDS)
    while not stop_event.is_set():
        try:
            await run_poll_cycle()
        except Exception as e:
            logger.error("[POLLER LOOP ERROR] Unexpected error: %s", str(e))

        try:
            # Sleep in 1-second increments so stop_event is checked promptly
            for _ in range(settings.POLLER_INTERVAL_SECONDS):
                if stop_event.is_set():
                    break
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            break

    logger.info("[POLLER] Background poller stopped cleanly.")
