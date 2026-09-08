"""The approval contract — a write that is held until a human decides.

An ``ApprovalRequest`` is what the person approving sees: who asked, which tool, and a bounded
preview of the arguments so the decision is informed. The preview is the ONE place raw arguments
are stored, and it is blanked the moment the request is decided; the audit ledger itself keeps
only the keyed payload hash, as always.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from gatekeeper.schemas.enums import ApprovalStatus

#: Max chars of the arguments shown to the approver (enough to decide, not a dump).
ARGUMENTS_PREVIEW_MAX = 500


class ApprovalRequest(BaseModel):
    """One held write, as stored in the approval queue."""

    id: str = Field(description="Short id a human types: `gatekeeper approve <id>`.")
    call_id: str
    ts: str = Field(description="UTC ISO-8601 when the call was held.")
    principal: str
    role: str
    upstream: str
    tool: str
    arguments_preview: str = Field(
        default="", description="Truncated JSON of the arguments; blanked once decided."
    )
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_by: str = ""
    decided_at: str = ""
    note: str = ""

    @property
    def is_final(self) -> bool:
        return self.status is not ApprovalStatus.PENDING
