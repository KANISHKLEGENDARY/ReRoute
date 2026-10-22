"""
Itinerary Decision Trace API Endpoint.

Provides full explainability audit trails:
`GET /api/v1/itinerary/{id}/trace`
Returns all stage-by-stage snapshots for an itinerary, ordered chronologically.
"""

from datetime import datetime
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.itinerary import Itinerary
from app.models.trace import DecisionTrace

router = APIRouter(prefix="/itinerary", tags=["Itinerary & Decision Traces"])


class StageTraceResponse(BaseModel):
    id: int
    event_id: str
    itinerary_id: int
    stage: str
    input_snapshot: Dict[str, Any]
    output_snapshot: Dict[str, Any]
    timestamp: datetime


@router.get("/{itinerary_id}/trace", response_model=Dict[str, List[StageTraceResponse]])
async def get_itinerary_decision_trace(
    itinerary_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Fetches the complete stage-by-stage decision trace audit log for a given trip,
    grouped by event_id, ordered by event then time.
    """
    # 1. Verify Itinerary exists
    itin_stmt = select(Itinerary).where(Itinerary.id == itinerary_id)
    itin_res = await db.execute(itin_stmt)
    itinerary = itin_res.scalars().first()

    if not itinerary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Itinerary with ID {itinerary_id} not found.",
        )

    # 2. Query all decision traces ordered chronologically
    trace_stmt = (
        select(DecisionTrace)
        .where(DecisionTrace.itinerary_id == itinerary_id)
        .order_by(DecisionTrace.timestamp.asc(), DecisionTrace.id.asc())
    )
    trace_res = await db.execute(trace_stmt)
    traces = trace_res.scalars().all()

    # 3. Group by event_id (dict preserves first-seen event order and chronological stages)
    grouped: Dict[str, List[StageTraceResponse]] = {}
    for trace in traces:
        evt_key = trace.event_id or "UNKNOWN"
        grouped.setdefault(evt_key, []).append(trace)

    return grouped
