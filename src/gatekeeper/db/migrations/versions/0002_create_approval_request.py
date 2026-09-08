"""create approval_request table (writes held for human approval)

Revision ID: 0002_create_approval_request
Revises: 0001_create_ledger
Create Date: 2026-09-08

Mirrors gatekeeper.db.models.ApprovalRequestRow / schemas.approval.ApprovalRequest.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_create_approval_request"
down_revision: str | None = "0001_create_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_request",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("ts", sa.String(), nullable=False),
        sa.Column("principal", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("upstream", sa.String(), nullable=False),
        sa.Column("tool", sa.String(), nullable=False),
        sa.Column("arguments_preview", sa.String(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(), nullable=False, server_default=""),
        sa.Column("decided_at", sa.String(), nullable=False, server_default=""),
        sa.Column("note", sa.String(), nullable=False, server_default=""),
    )
    op.create_index("ix_approval_request_call_id", "approval_request", ["call_id"])
    op.create_index("ix_approval_request_status", "approval_request", ["status"])


def downgrade() -> None:
    op.drop_index("ix_approval_request_status", table_name="approval_request")
    op.drop_index("ix_approval_request_call_id", table_name="approval_request")
    op.drop_table("approval_request")
