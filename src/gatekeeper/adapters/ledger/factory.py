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
from sqlalchemy import Engine, inspect
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


def _ensure_schema(engine: Engine, target: str) -> None:
    inspector = inspect(engine)
    if not all(inspector.has_table(t) for t in ("ledger_entry", "approval_request")):
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
