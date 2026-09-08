"""record which key signed each entry, and make retention accountable

Revision ID: 0004_key_id_and_checkpoints
Revises: 0003_approval_decided_method
Create Date: 2026-09-08

Two additions that together let an audit ledger survive real operations without giving up what
makes it worth having.

``ledger_entry.key_id`` names the HMAC key that signed a record — a fingerprint of the key, never
the key. Rotating the chain key used to make every earlier entry unverifiable; now `verify` picks
the right key per entry and walks straight through a rotation. Existing rows keep an empty key_id
and are verified with the current key (then any configured previous ones), so an existing ledger
keeps verifying with no migration of its contents. key_id is NOT part of the hashed payload, which
is what makes that backward compatibility possible.

``ledger_checkpoint`` is what a prune leaves behind: where the cut was, the chain's state at that
point, how many records went, and where they were archived — signed with the ledger key, so the
removal cannot be forged, edited, or backdated. Deleting records without leaving a valid signed
account of the deletion stays impossible.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_key_id_and_checkpoints"
down_revision: str | None = "0003_approval_decided_method"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ledger_entry", sa.Column("key_id", sa.String(), nullable=False, server_default="")
    )
    op.create_table(
        "ledger_checkpoint",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("through_seq", sa.Integer(), nullable=False),
        sa.Column("through_hash", sa.String(), nullable=False),
        sa.Column("pruned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("archive_path", sa.String(), nullable=False, server_default=""),
        sa.Column("note", sa.String(), nullable=False, server_default=""),
        sa.Column("key_id", sa.String(), nullable=False, server_default=""),
        sa.Column("checkpoint_hash", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ledger_checkpoint")
    op.drop_column("ledger_entry", "key_id")
