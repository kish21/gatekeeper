"""LLM port (M2): risk-classify a tool call. Implemented by adapters.llm.{claude,stub}."""

from __future__ import annotations

from typing import Protocol

from gatekeeper.schemas.models import RiskAssessment, ToolCall


class LLMProvider(Protocol):
    """Classify a call's risk for the write-approval gate.

    Async (network I/O). Contract: on timeout/error the caller fails closed to "requires approval"
    (ADR-005) — a classifier outage must never auto-allow a write.
    """

    async def classify(self, call: ToolCall) -> RiskAssessment: ...
