"""
Hotel Booking Model.

Stores hotel reservations linked to a traveler's itinerary.
Used by the agent's `adjust_hotel()` tool if a flight delay or cancellation
shifts the traveler's arrival time into the destination city.
Matches Section 4.5 of the Build Specification:
Table: `hotel_booking`
Key fields: id, itinerary_id (FK), hotel_name, confirmation_reference, 
            checkin_date, checkout_date, room_rate, currency, address
"""

from datetime import date
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.itinerary import Itinerary


class HotelBooking(Base, TimestampMixin):
    __tablename__ = "hotel_booking"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)

    # Foreign Key linking this hotel reservation to the trip itinerary
    itinerary_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("itinerary.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    hotel_name: Mapped[str] = mapped_column(String(255), nullable=False)
    confirmation_reference: Mapped[str] = mapped_column(String(100), nullable=False)

    checkin_date: Mapped[date] = mapped_column(Date, nullable=False)
    checkout_date: Mapped[date] = mapped_column(Date, nullable=False)

    room_rate: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)


    # Optional address / location
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Status: CONFIRMED, ADJUSTED, CANCELLED
    status: Mapped[str] = mapped_column(String(50), default="CONFIRMED", nullable=False)

    # Relationships
    itinerary: Mapped["Itinerary"] = relationship("Itinerary", back_populates="hotel_bookings")

    def __repr__(self) -> str:
        return f"<HotelBooking(id={self.id}, hotel='{self.hotel_name}', checkin={self.checkin_date}, status='{self.status}')>"
