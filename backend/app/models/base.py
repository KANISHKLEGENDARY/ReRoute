"""
Base Declarative Model for SQLAlchemy 2.0.

In modern SQLAlchemy 2.0, classes inherit from `DeclarativeBase` rather than 
the legacy `declarative_base()` function call. This enables standard Python typing, 
type hints with `Mapped[...]`, and static type analysis with tools like Mypy.
"""

from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    Parent base class for all database tables.
    Subclasses automatically get SQLAlchemy ORM mapping capabilities.
    """
    pass


class TimestampMixin:
    """
    A reusable mixin that adds `created_at` and `updated_at` timestamps to any model.
    
    Why use server_default=func.now()?
    - The timestamp is computed by the database server clock at the moment of row insertion,
      preventing drift or timezone mismatches caused by application server clocks.
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
