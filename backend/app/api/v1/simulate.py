"""
Disruption Event Simulation and Inspection Endpoints.

Handles:
- GET /api/v1/events (recent events from RESULT rows)
- GET /api/v1/events/{event_id} (all stages and result for an event)
- POST /api/v1/events/simulate (triggers synthetic events onto Redis with X-Demo-Key check)
"""

import os
from datetime import datetime
from typing import Optional
from uuid import uuid4
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.redis import publish_event
from app.models.flight_leg import FlightLeg
from app.models.trace import DecisionTrace
from app.schemas.pipeline import DisruptionType

router = APIRouter(prefix="/events", tags=["Simulation & Events"])
settings = get_settings()


class SimulateEventRequest(BaseModel):
    flight_leg_id: int = Field(description="Database ID of the flight leg to disrupt")
    event_type: DisruptionType = Field(default=DisruptionType.CANCELLED)
    delay_minutes: int = Field(default=0, ge=0)
    reason: Optional[str] = None
    notice_text: Optional[str] = Field(default=None, max_length=1000)
    traveler_preferences: Optional[str] = Field(default=None, max_length=500)


@router.get("", status_code=status.HTTP_200_OK)
async def list_recent_events(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Returns recent disruption events from RESULT trace rows, newest first."""
    safe_limit = max(1, min(limit, 50))
    stmt = (
        select(DecisionTrace)
        .where(DecisionTrace.stage == "RESULT")
        .order_by(DecisionTrace.timestamp.desc(), DecisionTrace.id.desc())
        .limit(safe_limit)
    )
    traces = (await db.execute(stmt)).scalars().all()
    events = []
    for t in traces:
        out = t.output_snapshot or {}
        events.append({
            "event_id": t.event_id,
            "itinerary_id": t.itinerary_id,
            "timestamp": t.timestamp.isoformat() if t.timestamp else None,
            "action": out.get("action", "UNKNOWN"),
            "policy_verdict": out.get("policy_verdict", "UNKNOWN"),
            "fare_delta_inr": out.get("fare_delta_inr", 0.0),
            "latency_ms": out.get("latency_ms", 0.0),
            "tokens_in": out.get("tokens_in", 0),
            "tokens_out": out.get("tokens_out", 0),
            "cost_usd": out.get("cost_usd", 0.0),
            "cost_inr": out.get("cost_inr", 0.0),
            "cost_estimated": out.get("cost_estimated", False),
            "llm_fallback": out.get("llm_fallback", False),
            "llm_fallback_reason": out.get("llm_fallback_reason", "none"),
            "result": out,
        })
    return events


@router.get("/{event_id}", status_code=status.HTTP_200_OK)
async def get_event_detail(event_id: str, db: AsyncSession = Depends(get_db)):
    """Returns all trace stages and the final result for a given event ID."""
    stmt = (
        select(DecisionTrace)
        .where(DecisionTrace.event_id == event_id)
        .order_by(DecisionTrace.timestamp.asc(), DecisionTrace.id.asc())
    )
    traces = (await db.execute(stmt)).scalars().all()
    if not traces:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Event {event_id} not found")

    stages = []
    result_snapshot = None
    for t in traces:
        stages.append({
            "id": t.id,
            "stage": t.stage,
            "input_snapshot": t.input_snapshot,
            "output_snapshot": t.output_snapshot,
            "timestamp": t.timestamp.isoformat() if t.timestamp else None,
        })
        if t.stage == "RESULT":
            result_snapshot = t.output_snapshot

    return {
        "event_id": event_id,
        "itinerary_id": traces[0].itinerary_id,
        "stages": stages,
        "result": result_snapshot,
    }


@router.post("/simulate", status_code=status.HTTP_200_OK)
async def simulate_disruption_event(
    request: SimulateEventRequest,
    x_demo_key: Optional[str] = Header(None, alias="X-Demo-Key"),
    db: AsyncSession = Depends(get_db),
):
    """Manually triggers a simulated disruption event after validating X-Demo-Key if set."""
    expected_demo_key = os.environ.get("DEMO_API_KEY") or getattr(settings, "DEMO_API_KEY", "")
    if expected_demo_key and (not x_demo_key or x_demo_key != expected_demo_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Demo-Key header")

    leg = (await db.execute(select(FlightLeg).where(FlightLeg.id == request.flight_leg_id))).scalars().first()
    if not leg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Flight leg {request.flight_leg_id} not found")

    event_id = f"SIM-{uuid4().hex[:8].upper()}"
    payload = {
        "event_id": event_id,
        "event_type": request.event_type.value,
        "flight_id": leg.id,
        "flight_number": f"{leg.airline_code}-{leg.flight_number}",
        "delay_minutes": request.delay_minutes,
        "reason": request.reason or f"Simulated {request.event_type.value} disruption via test control",
        "notice_text": request.notice_text,
        "traveler_preferences": request.traveler_preferences,
        "timestamp": datetime.utcnow().isoformat(),
    }
    published = await publish_event(settings.REDIS_CHANNEL, payload)
    return {"status": "published" if published else "fallback_dispatched", "event_id": event_id, "payload": payload}
