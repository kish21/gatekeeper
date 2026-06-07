"""SQLAlchemy declarative base. Concrete tables (the audit ledger) are defined in /contracts.

Kept separate so Alembic's ``env.py`` can import ``Base.metadata`` without pulling in app logic.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root of all ORM models. Empty until /contracts adds the LedgerEntry table."""


def database_url(ledger_path: str) -> str:
    """Build the SQLite URL from the configured ledger path (no hardcoded DB URL)."""
    return f"sqlite:///{ledger_path}"
