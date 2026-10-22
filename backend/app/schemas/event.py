"""
Pydantic Schemas for Event Payloads and Health Responses.

Why Pydantic Schemas?
- Pydantic validates data shapes at runtime for both incoming request bodies
  and outgoing HTTP responses.
- It automatically generates OpenAPI / Swagger documentation for FastAPI.
"""

from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class DisruptionEventSchema(BaseModel):
    """
    Schema for events published onto the Redis event bus.
    Used for both synthetic simulation triggers and background poller events.
    """
    event_type: str = Field(
        ...,
        description="Type of disruption event, e.g., 'CANCELLED', 'DELAYED', 'MISSED_CONNECTION', 'TEST'",
        examples=["CANCELLED"]
    )
    flight_id: Optional[int] = Field(
        default=None,
        description="Internal database ID of the affected FlightLeg record"
    )
    flight_number: Optional[str] = Field(
        default=None,
        description="Flight number code, e.g., '6E-204'"
    )
    details: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Additional context such as delay duration, weather alerts, or reason"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when the disruption event was generated"
    )


class HealthResponse(BaseModel):
    """
    Standard health check response schema.
    """
    status: str = Field(default="ok")
    project: str
    environment: str
    database_connected: bool
    redis_connected: bool
