"""
Persistent LLM Usage Counter Model.
Stores daily call attempt counts in PostgreSQL/database to survive stateless restarts.
"""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class LLMUsage(Base):
    """Stores daily API call attempts per model."""

    __tablename__ = "llm_usage"

    model: Mapped[str] = mapped_column(String(100), primary_key=True)
    day: Mapped[str] = mapped_column(String(20), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
