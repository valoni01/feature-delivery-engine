"""SQLAlchemy declarative base only — no engine or session (safe for Alembic imports)."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
