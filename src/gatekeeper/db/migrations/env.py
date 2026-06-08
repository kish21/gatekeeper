"""Alembic migration environment.

The DB URL is derived from the gateway config (config/platform.yaml -> ledger.path) so migrations
bootstrap from the SAME schema/target prod uses — no hardcoded connection string.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from gatekeeper.config.loader import get_settings, load_config
from gatekeeper.db import models  # noqa: F401 — register ORM models on Base.metadata
from gatekeeper.db.base import Base, database_url, ensure_parent_dir

config = context.config
target_metadata = Base.metadata


def _resolve_url() -> str:
    # An explicit url (set by tests/CI via Config) wins; otherwise derive from gateway config.
    override = config.get_main_option("sqlalchemy.url")
    if override:
        return override
    cfg = load_config(get_settings())
    ledger_path = cfg["platform"].get("ledger", {}).get("path", "./.gatekeeper/audit.db")
    ensure_parent_dir(ledger_path)  # SQLite can't create a DB in a missing dir
    return database_url(ledger_path)


def run_migrations_offline() -> None:
    context.configure(url=_resolve_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
