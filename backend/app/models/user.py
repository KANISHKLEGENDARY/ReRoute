"""
User Model.

Stores user credentials, contact details, and links to their registered itineraries.
Matches Section 4.5 of the Build Specification:
Table: `users`
Key fields: id, name, email, phone, password_hash, created_at
"""

from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.itinerary import Itinerary


class User(Base, TimestampMixin):
    __tablename__ = "users"

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)

    # Traveler's full name as it appears on their ticket
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Unique email address used for login and REAL email notifications (Section 7.5)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    # Optional phone number for SMS alerts
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Securely hashed password (bcrypt) - never store plaintext passwords
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Relationship: One user can have one or more itineraries
    # cascade="all, delete-orphan": if a user is deleted, all their itineraries are removed
    itineraries: Mapped[List["Itinerary"]] = relationship(
        "Itinerary",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}', name='{self.name}')>"
