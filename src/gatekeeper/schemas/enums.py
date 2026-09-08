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
