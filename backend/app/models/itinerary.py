"""
Itinerary Model.

Serves as the root container for a traveler's entire trip, linking together
all flight legs, hotel bookings, and autonomous decision traces.
Matches Section 4.5 of the Build Specification:
Table: `itinerary`
Key fields: id, user_id (FK), created_at
"""

from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.flight_leg import FlightLeg
    from app.models.hotel import HotelBooking
    from app.models.trace import DecisionTrace


class Itinerary(Base, TimestampMixin):
    __tablename__ = "itinerary"

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)

    # Foreign Key to the owning user
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Status of the overall itinerary: ACTIVE, DISRUPTED, REBOOKED, ESCALATED, COMPLETED
    status: Mapped[str] = mapped_column(String(50), default="ACTIVE", nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="itineraries")

    # One itinerary can have multiple flight legs (e.g. Leg 1: DEL -> DXB, Leg 2: DXB -> LHR)
    # lazy="selectin" pre-loads legs in a single secondary async query to avoid N+1 problems
    flight_legs: Mapped[List["FlightLeg"]] = relationship(
        "FlightLeg",
        back_populates="itinerary",
        cascade="all, delete-orphan",
        order_by="FlightLeg.leg_order",
        lazy="selectin"
    )

    # Linked hotel accommodations
    hotel_bookings: Mapped[List["HotelBooking"]] = relationship(
        "HotelBooking",
        back_populates="itinerary",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    # Audit history of autonomous agent decisions for this itinerary
    decision_traces: Mapped[List["DecisionTrace"]] = relationship(
        "DecisionTrace",
        back_populates="itinerary",
        cascade="all, delete-orphan",
        order_by="DecisionTrace.timestamp.desc()",
        lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Itinerary(id={self.id}, user_id={self.user_id}, status='{self.status}')>"
