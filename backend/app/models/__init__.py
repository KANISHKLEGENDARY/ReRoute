"""
Models Package Initialization.

Importing all models here ensures that when `Base.metadata.create_all` is called,
SQLAlchemy is aware of every table definition and foreign key relationship in the system.
"""

from app.models.base import Base, TimestampMixin
from app.models.user import User
from app.models.itinerary import Itinerary
from app.models.flight_leg import FlightLeg, PollLog
from app.models.hotel import HotelBooking
from app.models.trace import DecisionTrace

__all__ = [
    "Base",
    "TimestampMixin",
    "User",
    "Itinerary",
    "FlightLeg",
    "PollLog",
    "HotelBooking",
    "DecisionTrace",
]
