"""record HOW the approver of a held write was identified

Revision ID: 0003_approval_decided_method
Revises: 0002_create_approval_request
Create Date: 2026-09-08

"approved by priya" is only worth the proof behind the name. This column stores that proof
(oidc | token | console | local) next to the name, so an auditor reading an old decision can tell
whether the approver signed in or typed a name into a loopback page.

Existing rows keep an empty method: they were decided before the gateway recorded one, and
claiming otherwise would be a nicer-looking lie in an audit table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_approval_decided_method"
down_revision: str | None = "0002_create_approval_request"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "approval_request",
        sa.Column("decided_method", sa.String(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("approval_request", "decided_method")
