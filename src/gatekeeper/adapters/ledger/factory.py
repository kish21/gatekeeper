"""Open a configured ``SqliteLedgerStore``. Wiring only (keeps DB plumbing out of the CLI)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.config.loader import ConfigError, Settings, boot, ledger_path
from gatekeeper.db.base import database_url, ensure_parent_dir


def open_ledger(
    settings: Settings | None = None, config: dict[str, Any] | None = None
) -> SqliteLedgerStore:
    """Build the ledger store from config. Fail-closed (HMAC key) + fail-loud (table must exist).

    Pass an already-booted ``(settings, config)`` to avoid re-loading config + re-running the
    security guard (the gateway composition root does this); omit them to boot standalone (CLI).
    """
    if settings is None or config is None:
        settings, config = boot()  # validates GATEKEEPER_HMAC_KEY (fail-closed)
    path = ledger_path(config)
    try:
        ensure_parent_dir(path)
    except OSError as exc:
        # Almost always a wrong working directory: the relative ledger path resolved under a
        # protected dir (e.g. an MCP host launched the gateway without `cwd`). Turn the raw OSError
        # into a clear, caught ConfigError with the fix, instead of an opaque traceback.
        raise ConfigError(
            f"Cannot create the audit-ledger directory for {path!r} ({exc}). The gateway's working "
            "directory is likely wrong — set 'cwd' to the GateKeeperAI project folder in your MCP "
            "host config (e.g. Claude Desktop), then retry."
        ) from exc
    engine = create_engine(database_url(path))
    if not inspect(engine).has_table("ledger_entry"):
        raise ConfigError(
            "Ledger table not found. Run `make migrate` (alembic upgrade head) first."
        )
    return SqliteLedgerStore(Session(engine), settings.hmac_key)
