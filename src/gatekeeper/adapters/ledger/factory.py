"""Open a configured ``SqliteLedgerStore``. Wiring only (keeps DB plumbing out of the CLI).

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

from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.config.loader import ConfigError, Settings, boot, ledger_path
from gatekeeper.db.base import create_ledger_engine, database_url, ensure_parent_dir

#: Where the migration scripts live, inside the installed package (no repo checkout needed).
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


def migrate(ledger_db_path: str) -> None:
    """Bring the ledger schema at ``ledger_db_path`` to the latest migration (idempotent)."""
    ensure_parent_dir(ledger_db_path)
    # Alembic narrates every step at INFO; a first run should not read like a stack of logs.
    logging.getLogger("alembic").setLevel(logging.WARNING)
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", database_url(ledger_db_path))
    command.upgrade(cfg, "head")


def _ensure_schema(engine: Engine, path: str) -> None:
    if not inspect(engine).has_table("ledger_entry"):
        migrate(path)


def open_ledger(
    settings: Settings | None = None, config: dict[str, Any] | None = None
) -> SqliteLedgerStore:
    """Build the ledger store from config. Fail-closed (HMAC key); creates the schema if absent.

    Pass an already-booted ``(settings, config)`` to avoid re-loading config + re-running the
    security guard (the gateway composition root does this); omit them to boot standalone (CLI).
    """
    if settings is None or config is None:
        settings, config = boot()  # validates GATEKEEPER_HMAC_KEY (fail-closed)
    path = ledger_path(config)
    try:
        ensure_parent_dir(path)
    except OSError as exc:
        raise ConfigError(
            f"Cannot create the audit-ledger directory for {path!r} ({exc}). Set "
            "GATEKEEPER_CONFIG_DIR to the absolute path of the project's config/ folder in your "
            "MCP host config, or GATEKEEPER_LEDGER_PATH to a writable location, then retry."
        ) from exc
    engine = create_ledger_engine(path)
    try:
        _ensure_schema(engine, path)
    except Exception as exc:  # noqa: BLE001 — a schema failure must be a clear boot error
        raise ConfigError(
            f"Could not create or open the audit ledger at {path!r}: {type(exc).__name__}: {exc}"
        ) from exc
    return SqliteLedgerStore(Session(engine), settings.hmac_key)
