"""Approval port: the queue of writes waiting for a human. Implemented by adapters.approval."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from gatekeeper.schemas.approval import ApprovalRequest
from gatekeeper.schemas.enums import ApprovalStatus


class ApprovalQueue(Protocol):
    """Hold, look up, and decide approval requests.

    Contract: ``decide`` only moves a ``pending`` request to a final state and raises on any
    other transition (a decision cannot be changed or repeated); it records ``by`` together with
    the ``method`` that proved that name. ``get`` must return the latest state even when another
    process made the decision — the gateway polls it while it waits.
    """

    def create(self, request: ApprovalRequest) -> ApprovalRequest: ...

    def get(self, request_id: str) -> ApprovalRequest | None: ...

    def list_pending(self) -> Sequence[ApprovalRequest]: ...

    def decide(
        self,
        request_id: str,
        status: ApprovalStatus,
        *,
        by: str,
        note: str = "",
        method: str = "",
    ) -> ApprovalRequest: ...
