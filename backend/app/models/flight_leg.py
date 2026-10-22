"""
Flight Leg Model and Poll Log Model.

Stores individual legs of an itinerary (direct or multi-segment connections)
and the audit history of periodic flight-status checks.
Matches Section 4.5 of the Build Specification:
Table: `flight_leg`
Key fields: id, itinerary_id (FK), leg_order, airline_code, flight_number, pnr, 
            eticket_number, origin, destination, departure_datetime, cabin_class, 
            fare_paid, currency
Table: `poll_log`
Key fields: id, flight_leg_id (FK), status, checked_at
"""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.itinerary import Itinerary


class FlightLeg(Base, TimestampMixin):
    __tablename__ = "flight_leg"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)

    # Link back to parent itinerary
    itinerary_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("itinerary.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # 1 for first leg, 2 for connecting leg, etc.
    leg_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Airline / Carrier IATA code (e.g., "6E" for IndiGo, "AI" for Air India, "BA" for British Airways)
    airline_code: Mapped[str] = mapped_column(String(10), nullable=False)

    # Flight number (e.g., "6E-204" or "204")
    flight_number: Mapped[str] = mapped_column(String(20), index=True, nullable=False)

    # Booking Reference Locator (PNR) — used to identify the reservation
    pnr: Mapped[str] = mapped_column(String(20), nullable=False)

    # Optional E-ticket number
    eticket_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Airport IATA codes (e.g., "DEL", "BOM", "LHR", "JFK")
    origin: Mapped[str] = mapped_column(String(10), nullable=False)
    destination: Mapped[str] = mapped_column(String(10), nullable=False)

    # Scheduled departure and estimated arrival
    departure_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    arrival_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Cabin class: "Economy", "Premium Economy", "Business", "First"
    cabin_class: Mapped[str] = mapped_column(String(50), default="Economy", nullable=False)

    # Fare paid (numeric) — used by policy engine to compare against candidate alternatives
    fare_paid: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)


    # Current flight status: ON_TIME, DELAYED, CANCELLED, MISSED_CONNECTION, REBOOKED
    status: Mapped[str] = mapped_column(String(50), default="ON_TIME", nullable=False)

    # Relationships
    itinerary: Mapped["Itinerary"] = relationship("Itinerary", back_populates="flight_legs")
    poll_logs: Mapped[List["PollLog"]] = relationship(
        "PollLog",
        back_populates="flight_leg",
        cascade="all, delete-orphan",
        order_by="PollLog.checked_at.desc()",
        lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<FlightLeg(id={self.id}, flight='{self.airline_code}{self.flight_number}', route='{self.origin}->{self.destination}', status='{self.status}')>"


class PollLog(Base):
    """
    Audit log of flight-status polling events.
    Written on EVERY scheduled check (even routine ON_TIME polls) to populate
    the dashboard activity feed and demonstrate an active background watcher.
    """
    __tablename__ = "poll_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)

    flight_leg_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("flight_leg.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Status observed during this poll (e.g., "ON_TIME", "DELAYED_45M", "CANCELLED")
    status: Mapped[str] = mapped_column(String(50), nullable=False)

    # Timestamp of the check
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )

    # Relationship
    flight_leg: Mapped["FlightLeg"] = relationship("FlightLeg", back_populates="poll_logs")

    def __repr__(self) -> str:
        return f"<PollLog(id={self.id}, leg_id={self.flight_leg_id}, status='{self.status}', at={self.checked_at})>"
