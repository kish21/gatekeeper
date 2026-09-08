"""SQLAlchemy declarative base + the one place the ledger's SQLite engine is built.

Kept separate so Alembic's ``env.py`` can import ``Base.metadata`` without pulling in app logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root of all ORM models."""


#: How long a writer waits for a lock held by another process before failing (ms). A concurrent
#: ``gatekeeper tail`` / ``verify`` must never turn a governed call into "database is locked".
BUSY_TIMEOUT_MS = 5000


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


def create_ledger_engine(ledger_path: str) -> Engine:
    """The ledger's engine, configured for a hash-chained, append-only audit log:

    * **WAL journal** — readers never block the single writer, and an append is one fsync instead
      of two (the measured lever that brings governance overhead under its latency budget).
    * **``synchronous=FULL``** — an audit record that was acknowledged has reached the disk.
    * **``busy_timeout``** — a lock held briefly by another process (an operator running ``tail``)
      is waited out, not surfaced as a failed append.
    * **``BEGIN IMMEDIATE``** — every write transaction takes the write lock *before* reading the
      chain head, so two processes can never both read the same ``prev_hash`` and fork the chain.
      (pysqlite's default deferred BEGIN would allow exactly that race.)

    On a filesystem that cannot support WAL (some network mounts), SQLite keeps the previous
    journal mode; the durability and locking guarantees then depend on that filesystem.
    """
    engine = create_engine(database_url(ledger_path))

    @event.listens_for(engine, "connect")
    def _configure(dbapi_conn: Any, _record: Any) -> None:
        # We drive transactions ourselves (see "begin" below); disable pysqlite's implicit BEGIN.
        dbapi_conn.isolation_level = None
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _begin_immediate(conn: Any) -> None:
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine
