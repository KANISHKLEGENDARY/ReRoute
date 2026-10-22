"""
Health Check and Infrastructure Test Router.

Provides:
1. `GET /api/v1/health` - Probes database and Redis connectivity.
2. `POST /api/v1/health/test-event` - Publishes a fake event to prove Redis pub/sub wiring in Step 1.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.redis import get_redis_client, publish_event
from app.schemas.event import DisruptionEventSchema, HealthResponse

router = APIRouter(prefix="/health", tags=["Health & Diagnostics"])


@router.get(
    "",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="System Health Check",
    description="Probes the backend API, Async Database connection, and Redis event bus."
)
async def health_check(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    # 1. Probe Database Connection by executing a trivial SELECT 1 query
    db_ok = False
    try:
        result = await db.execute(text("SELECT 1"))
        if result.scalar() == 1:
            db_ok = True
    except Exception:
        db_ok = False

    # 2. Probe Redis Connection
    redis_ok = False
    try:
        client = await get_redis_client()
        if client is not None:
            await client.ping()
            redis_ok = True
    except Exception:
        redis_ok = False

    return HealthResponse(
        status="healthy" if db_ok else "degraded",
        project=settings.PROJECT_NAME,
        environment=settings.ENVIRONMENT,
        database_connected=db_ok,
        redis_connected=redis_ok,
    )


@router.post(
    "/test-event",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Publish Test Disruption Event",
    description="Publishes a test event onto the Redis channel to verify end-to-end event flow."
)
async def test_publish_event(
    event: DisruptionEventSchema,
    settings: Settings = Depends(get_settings),
):
    """
    Step 1 Verification Endpoint:
    Publishes an event payload to the configured Redis channel.
    The background listener will pick it up and log it to the console/logger.
    """
    payload = event.model_dump(mode="json")
    success = await publish_event(channel=settings.REDIS_CHANNEL, event_data=payload)
    
    return {
        "message": "Test event dispatched",
        "channel": settings.REDIS_CHANNEL,
        "payload": payload,
        "published": success
    }
