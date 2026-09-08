"""SQLAlchemy declarative base + the one place the ledger's engine is built.

Kept separate so Alembic's ``env.py`` can import ``Base.metadata`` without pulling in app logic.

The ledger runs on **SQLite** (one machine, one writer — the default) or on **PostgreSQL** (a
hosted deployment: durable across restarts and safe with more than one gateway replica). Which one
is chosen is a config value, not a code path the caller picks: ``GATEKEEPER_LEDGER_URL`` wins if
set, otherwise the ledger is the SQLite file at ``GATEKEEPER_LEDGER_PATH``. Everything above this
module speaks the same store API against either.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root of all ORM models."""


#: How long a writer waits for a lock held by another process before failing (ms). A concurrent
#: ``gatekeeper tail`` / ``verify`` must never turn a governed call into "database is locked".
BUSY_TIMEOUT_MS = 5000

#: Postgres advisory-lock id for the append path. Any connection appending to the chain takes this
#: lock for the duration of its transaction, so replicas serialize where SQLite uses BEGIN
#: IMMEDIATE. The number is arbitrary but must be stable — it IS the lock's identity.
CHAIN_LOCK_ID = 0x6741_7445  # "gAtE"

#: Seconds a replica waits for the chain lock before its append fails (and the call fails closed).
CHAIN_LOCK_TIMEOUT_MS = BUSY_TIMEOUT_MS


def is_url(target: str) -> bool:
    """True if ``target`` is a database URL rather than a filesystem path for the SQLite file."""
    return "://" in target


def normalize_url(url: str) -> str:
    """Pin the driver on a bare Postgres URL so a copy-pasted connection string just works.

    Azure (and most managed providers) hand out ``postgresql://…``; SQLAlchemy would then look for
    psycopg2, which we do not ship. We speak psycopg 3.
    """
    for bare, driver in (
        ("postgresql://", "postgresql+psycopg://"),
        ("postgres://", "postgresql+psycopg://"),
    ):
        if url.startswith(bare):
            return driver + url[len(bare) :]
    return url


def ensure_parent_dir(ledger_path: str) -> None:
    """Create the ledger file's parent directory if missing (SQLite only; a no-op for a URL).

    SQLite cannot create a DB inside a non-existent directory. The gateway owns its data dir, so it
    must create it rather than fail (or force the operator to ``mkdir`` first) — robustness for both
    fresh installs and CI.
    """
    if is_url(ledger_path):
        return
    Path(ledger_path).parent.mkdir(parents=True, exist_ok=True)


def database_url(target: str) -> str:
    """The SQLAlchemy URL for ``target`` — passed through if it already is one, else SQLite."""
    if is_url(target):
        return normalize_url(target)
    return f"sqlite:///{target}"


def create_ledger_engine(target: str) -> Engine:
    """The ledger's engine for a hash-chained, append-only audit log.

    **SQLite** (a path) is configured for a single writer on one machine:

    * **WAL journal** — readers never block the single writer, and an append is one fsync instead
      of two (the measured lever that brings governance overhead under its latency budget).
    * **``synchronous=FULL``** — an audit record that was acknowledged has reached the disk.
    * **``busy_timeout``** — a lock held briefly by another process (an operator running ``tail``)
      is waited out, not surfaced as a failed append.
    * **``BEGIN IMMEDIATE``** — every write transaction takes the write lock *before* reading the
      chain head, so two processes can never both read the same ``prev_hash`` and fork the chain.
      (pysqlite's default deferred BEGIN would allow exactly that race.)

    On a filesystem that cannot support WAL (some network mounts), SQLite keeps the previous
    journal mode; the durability and locking guarantees then depend on that filesystem. That is why
    a hosted deployment should use Postgres — see ``docs/features/durable-ledger.md``.

    **Postgres** (a URL) is configured for many replicas against one durable database:
    ``pool_pre_ping`` so a connection recycled by the platform's idle timeout is replaced rather
    than raising on the next append, and a bounded ``lock_timeout`` so a stuck peer degrades into a
    failed (fail-closed) call instead of a hung one. Serialization of the chain itself is the
    store's job — see ``lock_chain``.
    """
    url = database_url(target)
    if url.startswith("sqlite"):
        return _sqlite_engine(url)
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"options": f"-c lock_timeout={CHAIN_LOCK_TIMEOUT_MS}"},
    )


def _sqlite_engine(url: str) -> Engine:
    engine = create_engine(url)

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


def is_postgres(engine: Any) -> bool:
    """True when this engine talks to Postgres (the multi-replica ledger)."""
    return bool(getattr(getattr(engine, "dialect", None), "name", "") == "postgresql")


def lock_chain(session: Any) -> None:
    """Serialize the append path so two writers can never read the same chain head.

    SQLite already does this: its engine opens every write transaction with ``BEGIN IMMEDIATE``, so
    the write lock is held before the head is read. Postgres has no such per-transaction file lock,
    and a hosted deployment runs more than one replica, so an appending transaction takes a
    **transaction-scoped advisory lock** first. It is released by the commit or the rollback — a
    replica that dies mid-append cannot wedge the chain — and it never blocks readers.
    """
    if is_postgres(session.get_bind()):
        session.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": CHAIN_LOCK_ID})


def redact_url(target: str) -> str:
    """A ledger target safe to print: the password in a Postgres URL is replaced, never echoed.

    Connection strings reach error messages, ``doctor`` output and logs. A managed database hands
    out its password inside the URL, so redaction happens here — once — rather than at each caller.
    """
    if not is_url(target):
        return target
    scheme, _, rest = target.partition("://")
    credentials, at, hostpart = rest.rpartition("@")
    if not at:
        return target
    user, _, _password = credentials.partition(":")
    return f"{scheme}://{user}:***@{hostpart}"


def backend_name(target: str) -> str:
    """A short, human-readable name for the configured ledger backend (for ``doctor``/logs)."""
    return "postgres" if database_url(target).startswith("postgresql") else "sqlite"
