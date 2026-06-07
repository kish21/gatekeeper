"""SQLAlchemy declarative base. Concrete tables (the audit ledger) are defined in /contracts.

Kept separate so Alembic's ``env.py`` can import ``Base.metadata`` without pulling in app logic.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root of all ORM models. Empty until /contracts adds the LedgerEntry table."""


def ensure_parent_dir(ledger_path: str) -> None:
    """Create the ledger file's parent directory if missing.

    SQLite cannot create a DB inside a non-existent directory. The gateway owns its data dir, so it
    must create it rather than fail (or force the operator to ``mkdir`` first) — robustness for both
    fresh installs and CI.
    """
    Path(ledger_path).parent.mkdir(parents=True, exist_ok=True)


def database_url(ledger_path: str) -> str:
    """Build the SQLite URL from the configured ledger path (no hardcoded DB URL)."""
    return f"sqlite:///{ledger_path}"
