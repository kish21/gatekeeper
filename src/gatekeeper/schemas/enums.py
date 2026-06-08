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
