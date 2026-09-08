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
    # Happy path: a writable dir + an already-migrated ledger yields a usable store (no error).
    # Built through the migrations, like every real ledger: a schema created any other way is a
    # state the product cannot produce, and pretending otherwise hides the upgrade path below.
    db = tmp_path / "audit.db"
    factory.migrate(str(db))
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


def test_an_existing_ledger_is_upgraded_when_the_schema_moves_on(tmp_path: Path) -> None:
    """A ledger created by an older version must migrate itself on open, not fail on every write.

    Checking only that the tables EXIST was not enough, and the failure mode was ugly: an install
    that had been running for months already had them, so a migration adding a column never ran
    and every append then failed against the missing column. This pins the fix, and the promise
    that comes with it — records written under the old schema still verify afterwards.
    """
    import sqlalchemy as sa
    from alembic.script import ScriptDirectory

    from gatekeeper.adapters.ledger.sql import SqlLedgerStore
    from gatekeeper.schemas.enums import ActionKind, Verdict
    from gatekeeper.schemas.ledger import LedgerEntry

    db = str(tmp_path / "old.db")
    factory.migrate(db)

    # Wind the ledger back to how an older install looks: the key_id column and the checkpoint
    # table did not exist, and alembic recorded the revision before them.
    engine = sa.create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE ledger_entry DROP COLUMN key_id"))
        conn.execute(sa.text("DROP TABLE ledger_checkpoint"))
        conn.execute(
            sa.text("UPDATE alembic_version SET version_num = '0003_approval_decided_method'")
        )
    engine.dispose()

    settings = Settings(hmac_key="k" * 64)
    config: dict[str, Any] = {"platform": {"ledger": {"path": db}}}
    store = factory.open_ledger(settings, config)
    try:
        head = ScriptDirectory(str(factory.MIGRATIONS_DIR)).get_current_head()
        with sa.create_engine(f"sqlite:///{db}").connect() as conn:
            at = conn.execute(sa.text("select version_num from alembic_version")).scalar_one()
        assert at == head, "opening an out-of-date ledger must bring it to head"

        # and the upgraded ledger works: it can be written to, and it verifies.
        store.append(
            LedgerEntry(
                call_id="after-upgrade",
                ts="2026-09-08T10:00:00+00:00",
                principal="alice",
                role="operator",
                upstream="demo",
                tool="write_file",
                action_kind=ActionKind.WRITE,
                verdict=Verdict.ALLOW,
                reason="written after the upgrade",
                payload_hash="a" * 64,
            )
        )
        assert store.verify().ok is True
    finally:
        store.close()
    assert isinstance(store, SqlLedgerStore)
