"""create ledger_entry table (the tamper-evident audit log)

Revision ID: 0001_create_ledger
Revises:
Create Date: 2026-06-07

Mirrors gatekeeper.db.models.LedgerEntryRow / schemas.ledger.LedgerEntry. Index + constraint names
match the ORM metadata so `alembic revision --autogenerate` reports no drift.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_create_ledger"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ledger_entry",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("ts", sa.String(), nullable=False),
        sa.Column("tenant", sa.String(), nullable=False, server_default="default"),
        sa.Column("principal", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("upstream", sa.String(), nullable=False),
        sa.Column("tool", sa.String(), nullable=False),
        sa.Column("action_kind", sa.String(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("payload_hash", sa.String(), nullable=False),
        sa.Column("result_summary", sa.String(), nullable=False, server_default=""),
        sa.Column("risk", sa.Float(), nullable=True),
        sa.Column("prev_hash", sa.String(), nullable=False),
        sa.Column("entry_hash", sa.String(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("entry_hash", name="uq_ledger_entry_hash"),
    )
    op.create_index("ix_ledger_entry_call_id", "ledger_entry", ["call_id"])
    op.create_index("ix_ledger_entry_ts", "ledger_entry", ["ts"])
    op.create_index("ix_ledger_entry_tenant", "ledger_entry", ["tenant"])
    op.create_index("ix_ledger_principal_ts", "ledger_entry", ["principal", "ts"])


def downgrade() -> None:
    op.drop_index("ix_ledger_principal_ts", table_name="ledger_entry")
    op.drop_index("ix_ledger_entry_tenant", table_name="ledger_entry")
    op.drop_index("ix_ledger_entry_ts", table_name="ledger_entry")
    op.drop_index("ix_ledger_entry_call_id", table_name="ledger_entry")
    op.drop_table("ledger_entry")
