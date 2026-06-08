"""Integration: the Alembic migration applies and the built schema matches the ORM."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from gatekeeper.db.models import LedgerEntryRow


def test_migration_applies_and_schema_matches_code(tmp_path):
    url = f"sqlite:///{tmp_path / 'audit.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)  # override -> temp DB (see env.py)

    command.upgrade(cfg, "head")  # run the actual migration

    insp = sa.inspect(sa.create_engine(url))
    assert insp.has_table("ledger_entry")
    db_cols = {c["name"] for c in insp.get_columns("ledger_entry")}
    orm_cols = {c.name for c in LedgerEntryRow.__table__.columns}
    assert orm_cols == db_cols, f"schema<->code drift: {orm_cols ^ db_cols}"
    # the tamper-evidence column the verify path relies on must be uniquely constrained
    uniques = {u["name"] for u in insp.get_unique_constraints("ledger_entry")}
    assert "uq_ledger_entry_hash" in uniques
