"""Unit — opening the ledger turns an unwritable directory into a clear, caught ConfigError.

If the gateway runs with the wrong working directory (e.g. an MCP host launched it without ``cwd``),
the relative ledger path resolves under a protected dir and ``mkdir`` raises ``OSError``.
That must surface as a ``ConfigError`` with a fix hint (caught by ``serve``, shown on stderr) — not
an opaque traceback the user can't act on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from gatekeeper.adapters.ledger import factory
from gatekeeper.config.loader import ConfigError, Settings


def _raise_permission_error(_path: str) -> None:
    raise PermissionError("[WinError 5] Access is denied: '.gatekeeper'")


def test_open_ledger_maps_unwritable_dir_to_configerror_with_config_dir_hint(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(factory, "ensure_parent_dir", _raise_permission_error)
    settings = Settings(hmac_key="k" * 64)
    config: dict[str, Any] = {"platform": {"ledger": {"path": "./.gatekeeper/audit.db"}}}

    with pytest.raises(ConfigError, match="GATEKEEPER_CONFIG_DIR"):
        factory.open_ledger(settings, config)


def test_open_ledger_opens_an_existing_ledger(tmp_path: Path) -> None:
    # Happy path: a writable dir + a migrated table yields a usable store (no error).
    import sqlalchemy as sa

    from gatekeeper.db.base import Base

    db = tmp_path / "audit.db"
    Base.metadata.create_all(sa.create_engine(f"sqlite:///{db}"))
    settings = Settings(hmac_key="k" * 64)
    config: dict[str, Any] = {"platform": {"ledger": {"path": str(db)}}}

    store = factory.open_ledger(settings, config)
    try:
        assert store.verify().ok  # empty chain verifies; the store is usable
    finally:
        store.close()


def test_open_ledger_creates_the_schema_when_missing(tmp_path: Path) -> None:
    # A fresh checkout has no ledger yet; opening it must migrate, not demand a separate step.
    db = tmp_path / "fresh" / "audit.db"
    settings = Settings(hmac_key="k" * 64)
    config: dict[str, Any] = {"platform": {"ledger": {"path": str(db)}}}

    store = factory.open_ledger(settings, config)
    try:
        assert db.is_file()
        assert store.verify().ok
    finally:
        store.close()
    # And the migration is the schema's single source: alembic knows the DB is at head. The head
    # is read from the migration scripts rather than pinned here, so adding a migration does not
    # need this test edited — only a ledger that stopped migrating itself should fail it.
    import sqlalchemy as sa
    from alembic.script import ScriptDirectory

    head = ScriptDirectory(str(factory.MIGRATIONS_DIR)).get_current_head()
    versions = (
        sa.create_engine(f"sqlite:///{db}")
        .connect()
        .execute(sa.text("select version_num from alembic_version"))
        .all()
    )
    assert versions == [(head,)]
