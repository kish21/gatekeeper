"""Open a configured ``SqlLedgerStore``. Wiring only (keeps DB plumbing out of the CLI).

A ledger that does not exist yet is created here by running the migrations, so ``serve``,
``tail`` and ``verify`` all work on a fresh checkout without a separate migrate step. The
migrations remain the single source of the schema (``gatekeeper.db.migrations``); this module only
decides *when* to run them.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from gatekeeper.adapters.ledger.sql import SqlLedgerStore
from gatekeeper.config.loader import (
    ConfigError,
    Settings,
    boot,
    ledger_target,
    previous_hmac_keys,
)
from gatekeeper.db.base import (
    backend_name,
    create_ledger_engine,
    database_url,
    ensure_parent_dir,
    redact_url,
)

#: Where the migration scripts live, inside the installed package (no repo checkout needed).
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


def migrate(target: str) -> None:
    """Bring the schema at ``target`` (a SQLite path or a Postgres URL) to head. Idempotent."""
    ensure_parent_dir(target)
    # Alembic narrates every step at INFO; a first run should not read like a stack of logs.
    logging.getLogger("alembic").setLevel(logging.WARNING)
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", database_url(target).replace("%", "%%"))
    command.upgrade(cfg, "head")


def _current_revision(engine: Engine) -> str | None:
    """The migration this ledger is at, or ``None`` if it has never been migrated."""
    inspector = inspect(engine)
    if not inspector.has_table("alembic_version"):
        return None
    with engine.connect() as connection:
        row = connection.execute(text("select version_num from alembic_version")).first()
    return str(row[0]) if row else None


def _ensure_schema(engine: Engine, target: str) -> None:
    """Bring an existing ledger up to date, and create a missing one.

    Checking only that the TABLES exist was not enough: a ledger created by an older version
    already has them, so a migration that adds a column would never run and every append would
    fail against the missing column. Comparing the recorded revision against the migrations
    shipped in this package catches that — an upgrade migrates itself on first open, exactly as a
    fresh install does, which is what makes "no separate migrate step" true for BOTH.
    """
    head = ScriptDirectory(str(MIGRATIONS_DIR)).get_current_head()
    if _current_revision(engine) != head:
        migrate(target)


def open_ledger(
    settings: Settings | None = None, config: dict[str, Any] | None = None
) -> SqlLedgerStore:
    """Build the ledger store from config. Fail-closed (HMAC key); creates the schema if absent.

    Pass an already-booted ``(settings, config)`` to avoid re-loading config + re-running the
    security guard (the gateway composition root does this); omit them to boot standalone (CLI).
    """
    if settings is None or config is None:
        settings, config = boot()  # validates GATEKEEPER_HMAC_KEY (fail-closed)
    target = ledger_target(config)
    try:
        ensure_parent_dir(target)
    except OSError as exc:
        raise ConfigError(
            f"Cannot create the audit-ledger directory for {target!r} ({exc}). Set "
            "GATEKEEPER_CONFIG_DIR to the absolute path of the project's config/ folder in your "
            "MCP host config, or GATEKEEPER_LEDGER_PATH to a writable location, then retry."
        ) from exc
    engine = create_ledger_engine(target)
    try:
        _ensure_schema(engine, target)
    except Exception as exc:  # noqa: BLE001 — a schema failure must be a clear boot error
        raise ConfigError(
            f"Could not create or open the {backend_name(target)} audit ledger "
            f"({redact_url(target)}): {type(exc).__name__}: {exc}"
        ) from exc
    return SqlLedgerStore(Session(engine), settings.hmac_key, previous_hmac_keys(settings))
