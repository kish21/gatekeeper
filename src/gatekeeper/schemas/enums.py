"""Enumerated boundary values. String-valued so they serialize cleanly into JSON + the ledger."""

from __future__ import annotations

from enum import StrEnum


class ActionKind(StrEnum):
    """Whether a tool call reads or mutates. ``unknown`` until classified (config or M2 LLM)."""

    READ = "read"
    WRITE = "write"
    UNKNOWN = "unknown"


class Verdict(StrEnum):
    """The governance outcome for a call. Default everywhere is DENY (fail-closed)."""

    ALLOW = "allow"
    DENY = "deny"
    PENDING = "pending"  # held for human approval; always followed by an allow or a deny entry


class ApprovalStatus(StrEnum):
    """Lifecycle of a held write. Only ``pending`` can change; every other state is final."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"  # nobody decided within the timeout -> treated as a deny
    CANCELLED = "cancelled"  # the caller went away while waiting -> never forwarded


class ApproverMethod(StrEnum):
    """How the person who decided a held write was identified — recorded on the decision.

    An audit trail that says "approved by priya" is worth only as much as the proof behind the
    name, so the proof is part of the record rather than an assumption about the deployment.
    """

    OIDC = "oidc"  # a corporate login validated against the IdP's keys — the strongest
    # a personal bearer token that resolves to a named principal and role
    TOKEN = "token"  # noqa: S105 — the NAME of a proof method, not a credential
    CONSOLE = "console"  # someone with a shell on the gateway host (`gatekeeper approve`)
    LOCAL = "local"  # a name typed on a loopback desk with no identity configured — dev only

    @property
    def is_verified(self) -> bool:
        """True when the name on the decision was proven, not asserted."""
        return self in (ApproverMethod.OIDC, ApproverMethod.TOKEN)
