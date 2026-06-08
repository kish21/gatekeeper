"""Upstream port: forward an approved call to a real MCP server (adapters.upstream.*)."""

from __future__ import annotations

from typing import Protocol

from gatekeeper.schemas.models import ToolCall, ToolResult


class UpstreamClient(Protocol):
    """Forward a governed call to its upstream and return the result.

    Async because it is network I/O (ADR-004: timeout, retry-transient-only, circuit-breaker).
    Contract: a forward is attempted ONLY after the call was allowed + audited.
    """

    async def forward(self, call: ToolCall) -> ToolResult: ...
