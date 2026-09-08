"""The approval contract — a write that is held until a human decides.

An ``ApprovalRequest`` is what the person approving sees: who asked, which tool, and a bounded
preview of the arguments so the decision is informed. The preview is the ONE place raw arguments
are stored, and it is blanked the moment the request is decided; the audit ledger itself keeps
only the keyed payload hash, as always.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from gatekeeper.schemas.enums import ApprovalStatus, ApproverMethod

#: Max chars of the arguments shown to the approver (enough to decide, not a dump).
ARGUMENTS_PREVIEW_MAX = 500


class Approver(BaseModel):
    """The person deciding a held write, and the strength of the proof that it is them.

    ``id`` is what the ledger will name. ``method`` is how that name was established — a corporate
    login, their own bearer token, a shell on the gateway host, or (loopback development only) a
    name typed into the page. The audit record carries both, so nobody has to guess later how much
    an approval is worth.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=120)
    role: str = Field(default="", description="Gateway role, when the identity carries one.")
    method: ApproverMethod

    @property
    def is_console(self) -> bool:
        return self.method is ApproverMethod.CONSOLE

    def describe(self) -> str:
        """How this approver appears in the ledger, e.g. ``priya.n (oidc)`` — proof included."""
        return f"{self.id} ({self.method.value})"


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
    decided_method: str = Field(
        default="", description="How the approver was identified (ApproverMethod), or empty."
    )
    decided_at: str = ""
    note: str = ""

    @property
    def is_final(self) -> bool:
        return self.status is not ApprovalStatus.PENDING
