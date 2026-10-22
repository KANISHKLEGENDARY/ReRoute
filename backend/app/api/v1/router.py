"""
API v1 Router Aggregator.

Consolidates all modular sub-routers under the `/api/v1` prefix.
As we proceed through the steps (Auth in Step 2, Simulate in Step 4, etc.),
their routers will be included here cleanly.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.flight_leg import FlightLeg
from app.api.v1.health import router as health_router
from app.api.v1.simulate import router as simulate_router
from app.api.v1.metrics import router as metrics_router
from app.api.v1.trace import router as trace_router
from app.api.v1.websocket import router as websocket_router

api_v1_router = APIRouter(prefix="/api/v1")

# Include sub-routers
api_v1_router.include_router(health_router)
api_v1_router.include_router(simulate_router)
api_v1_router.include_router(metrics_router)
api_v1_router.include_router(trace_router)
api_v1_router.include_router(websocket_router)


@api_v1_router.get("/legs", tags=["Flight Legs"])
async def list_flight_legs(db: AsyncSession = Depends(get_db)):
    """Returns all flight legs for the Simulate scenario trigger dropdown."""
    stmt = select(FlightLeg).order_by(FlightLeg.id.asc())
    res = await db.execute(stmt)
    legs = res.scalars().all()
    return [
        {
            "id": leg.id,
            "flight_number": f"{leg.airline_code}-{leg.flight_number}",
            "airline_code": leg.airline_code,
            "origin": leg.origin,
            "destination": leg.destination,
            "departure_datetime": leg.departure_datetime.isoformat() if leg.departure_datetime else None,
            "arrival_datetime": leg.arrival_datetime.isoformat() if leg.arrival_datetime else None,
            "status": leg.status,
            "fare_paid": leg.fare_paid,
        }
        for leg in legs
    ]

