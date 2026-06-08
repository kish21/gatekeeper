"""ORM persistence models. The physical schema is built by Alembic migrations (never hand-edited);
this metadata must stay in lockstep with the migration so ``--autogenerate`` shows no drift.

``LedgerEntryRow`` mirrors ``schemas.ledger.LedgerEntry`` field-for-field.
"""

from __future__ import annotations

from sqlalchemy import Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from gatekeeper.db.base import Base
from gatekeeper.schemas.ledger import LEDGER_SCHEMA_VERSION


class LedgerEntryRow(Base):
    """A persisted tamper-evident audit entry (table ``ledger_entry``)."""

    __tablename__ = "ledger_entry"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    ts: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tenant: Mapped[str] = mapped_column(String, nullable=False, default="default", index=True)
    principal: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    upstream: Mapped[str] = mapped_column(String, nullable=False)
    tool: Mapped[str] = mapped_column(String, nullable=False)
    action_kind: Mapped[str] = mapped_column(String, nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String, nullable=False)
    result_summary: Mapped[str] = mapped_column(String, nullable=False, default="")
    risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    prev_hash: Mapped[str] = mapped_column(String, nullable=False)
    entry_hash: Mapped[str] = mapped_column(String, nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=LEDGER_SCHEMA_VERSION
    )

    __table_args__ = (
        UniqueConstraint("entry_hash", name="uq_ledger_entry_hash"),
        Index("ix_ledger_principal_ts", "principal", "ts"),
    )
