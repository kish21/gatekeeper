"""Open a configured ``SqliteLedgerStore``. Wiring only (keeps DB plumbing out of the CLI)."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.config.loader import ConfigError, boot, ledger_path
from gatekeeper.db.base import database_url, ensure_parent_dir


def open_ledger() -> SqliteLedgerStore:
    """Build the ledger store from config. Fail-closed (HMAC key) + fail-loud (table must exist)."""
    settings, config = boot()  # validates GATEKEEPER_HMAC_KEY (fail-closed)
    path = ledger_path(config)
    ensure_parent_dir(path)
    engine = create_engine(database_url(path))
    if not inspect(engine).has_table("ledger_entry"):
        raise ConfigError(
            "Ledger table not found. Run `make migrate` (alembic upgrade head) first."
        )
    return SqliteLedgerStore(Session(engine), settings.hmac_key)
