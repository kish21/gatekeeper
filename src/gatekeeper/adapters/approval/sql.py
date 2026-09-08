"""SQL ``ApprovalQueue`` — the held-writes table in the ledger's own database.

Sharing the database means one place to back up and one lock to reason about; the gateway process
waits on a request while ``gatekeeper approve``, the desk, or another replica decides it. Every
read here ends its transaction immediately so a waiting gateway sees the other process's commit on
its next poll (a lingering read transaction would pin a stale snapshot). Works on SQLite (one
machine) and Postgres (many replicas) — see ``gatekeeper.db.base``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from gatekeeper.db.models import ApprovalRequestRow
from gatekeeper.schemas.approval import ApprovalRequest
from gatekeeper.schemas.enums import ApprovalStatus


class ApprovalStateError(RuntimeError):
    """The request is not pending (already decided, expired, or unknown)."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SqlApprovalQueue:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _to_request(row: ApprovalRequestRow) -> ApprovalRequest:
        return ApprovalRequest.model_validate(row, from_attributes=True)

    def create(self, request: ApprovalRequest) -> ApprovalRequest:
        row = ApprovalRequestRow(**request.model_dump(mode="json"))
        try:
            self._session.add(row)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return request

    def get(self, request_id: str) -> ApprovalRequest | None:
        try:
            row = self._session.get(ApprovalRequestRow, request_id, populate_existing=True)
            return self._to_request(row) if row is not None else None
        finally:
            self._session.rollback()  # end the read transaction: the next poll must see new commits

    def list_pending(self) -> Sequence[ApprovalRequest]:
        try:
            rows = (
                self._session.execute(
                    select(ApprovalRequestRow)
                    .where(ApprovalRequestRow.status == ApprovalStatus.PENDING.value)
                    .order_by(ApprovalRequestRow.ts.asc())
                    .execution_options(populate_existing=True)
                )
                .scalars()
                .all()
            )
            return [self._to_request(r) for r in rows]
        finally:
            self._session.rollback()

    def decide(
        self,
        request_id: str,
        status: ApprovalStatus,
        *,
        by: str,
        note: str = "",
        method: str = "",
    ) -> ApprovalRequest:
        if status is ApprovalStatus.PENDING:
            raise ApprovalStateError("a decision must be a final status")
        try:
            # Lock the row for the transaction so two approvers deciding the same request at the
            # same moment cannot both pass the pending check: the second one waits, then sees the
            # first one's decision and is refused. (SQLite ignores FOR UPDATE — its whole write
            # transaction is already exclusive, which gives the same guarantee.)
            row = self._session.get(
                ApprovalRequestRow, request_id, populate_existing=True, with_for_update=True
            )
            if row is None:
                raise ApprovalStateError(f"no approval request {request_id!r}")
            if row.status != ApprovalStatus.PENDING.value:
                raise ApprovalStateError(
                    f"request {request_id} is already {row.status}"
                    + (f" (by {row.decided_by})" if row.decided_by else "")
                )
            row.status = status.value
            row.decided_by = by
            row.decided_method = method
            row.decided_at = _now()
            row.note = note
            row.arguments_preview = ""  # the preview served its purpose; do not keep raw args
            self._session.commit()
            return self._to_request(row)
        except Exception:
            self._session.rollback()
            raise

    def close(self) -> None:
        self._session.close()
