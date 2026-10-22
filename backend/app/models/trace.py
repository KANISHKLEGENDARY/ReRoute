"""
Decision Trace Model.

Stores step-by-step audit logs of the AI Agent and Policy Engine reasoning process.
Matches Section 4.5 of the Build Specification:
Table: `decision_trace`
Key fields: id, itinerary_id (FK), stage, input_snapshot, output_snapshot, timestamp

Why is Decision Trace central to this project?
1. Explainability: The frontend uses this to show travelers 'Why this option was selected'.
2. Metrics: `GET /metrics` aggregates these timestamped rows to calculate detection latency,
   decision latency, and rebooking success rates dynamically.
3. Live Demo / Interviews: Proves autonomous execution pipeline stages are real and inspectable.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.itinerary import Itinerary


class DecisionTrace(Base):
    __tablename__ = "decision_trace"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)

    # Event ID correlating all decision stages for a single disruption event
    event_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Link to the itinerary affected
    itinerary_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("itinerary.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Pipeline stage name:
    # - "DISRUPTION_DETECTED"
    # - "SEARCH_ALTERNATIVES"
    # - "POLICY_EVALUATION"
    # - "EXECUTE_REBOOKING"
    # - "HOTEL_ADJUSTMENT"
    # - "NOTIFICATION"
    # - "ESCALATION"
    stage: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Structured JSON snapshot of the inputs provided to this step
    input_snapshot: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Structured JSON snapshot of the decision, reasoning, or confirmation response
    output_snapshot: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Exact timestamp of when this decision stage executed
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )

    # Relationship
    itinerary: Mapped["Itinerary"] = relationship("Itinerary", back_populates="decision_traces")

    def __repr__(self) -> str:
        return f"<DecisionTrace(id={self.id}, event_id='{self.event_id}', itinerary_id={self.itinerary_id}, stage='{self.stage}', timestamp={self.timestamp})>"
