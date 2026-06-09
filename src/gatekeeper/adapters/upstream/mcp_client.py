"""MCP-client ``UpstreamClient`` — forwards a governed call to a real upstream MCP server.

Implements ``ports.upstream.UpstreamClient``. The ONLY layer allowed to import the MCP SDK on the
upstream side (ports & adapters / ADR-004). Holds ONE persistent, lazily-opened session per upstream
(re-launching a stdio server per call would be slow and lose its state) and serializes calls to each
session with a lock (a single stdio pipe is request/response, not concurrent).

Resilience (ADR-004): a per-call timeout; any failure is converted to a non-raising ``ToolResult``
with ``ok=False`` so the agent never hangs and the pipeline can still AUDIT the outcome (fail-closed
without un-audited bypass). ``summary`` is redacted/truncated — raw output is relayed live via
``ToolResult.raw`` but never persisted.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from gatekeeper.infra.logging import get_logger
from gatekeeper.schemas.models import ToolCall, ToolResult

_log = get_logger("gatekeeper.upstream")

#: Max chars of an upstream result kept in the audit summary (raw output is never persisted).
_SUMMARY_MAX = 200


@dataclass(frozen=True)
class UpstreamSpec:
    """How to reach one registered upstream (from ``config/upstreams.yaml``)."""

    name: str
    transport: str
    command: tuple[str, ...] = ()
    env: Mapping[str, str] | None = None
    cwd: str | None = None

    @classmethod
    def from_config(cls, raw: Mapping[str, Any]) -> UpstreamSpec:
        env = raw.get("env")
        return cls(
            name=str(raw["name"]),
            transport=str(raw.get("transport", "stdio")),
            command=tuple(str(part) for part in raw.get("command", [])),
            env={str(k): str(v) for k, v in env.items()} if env else None,
            cwd=str(raw["cwd"]) if raw.get("cwd") else None,
        )

    def stdio_params(self) -> StdioServerParameters:
        if self.transport != "stdio":
            raise NotImplementedError(
                f"upstream {self.name!r}: transport {self.transport!r} not supported yet "
                "(stdio only this slice; HTTP is a fast-follow)."
            )
        if not self.command:
            raise ValueError(f"upstream {self.name!r}: stdio transport needs a 'command'.")
        return StdioServerParameters(
            command=self.command[0],
            args=list(self.command[1:]),
            env=dict(self.env) if self.env else None,
            cwd=self.cwd,
        )


def _summarize(result: types.CallToolResult) -> str:
    """Status-only summary for the ledger — metadata, NOT the raw output body (PII stance).

    A successful result records only shape (block count + total text length): the actual content
    is relayed live to the agent via ``ToolResult.raw`` but is never written to the audit log, so a
    governed read of a secret file leaves no plaintext in the ledger. An error records a truncated
    diagnostic message (errors carry *why*, which is the point of auditing them) capped at
    ``_SUMMARY_MAX``.
    """
    block_count = len(result.content)
    if result.isError:
        first = next((b.text for b in result.content if isinstance(b, types.TextContent)), "")
        message = first[:_SUMMARY_MAX]
        return f"error: {message}" if message else "error"
    text_len = sum(len(b.text) for b in result.content if isinstance(b, types.TextContent))
    return f"ok: {block_count} block(s), {text_len} chars"


class McpUpstreamClient:
    """Forward calls to registered upstreams over the MCP SDK, one persistent session each."""

    def __init__(self, specs: Sequence[UpstreamSpec], *, timeout: float = 30.0) -> None:
        self._specs = {spec.name: spec for spec in specs}
        self._timeout = timeout
        self._stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        # Per-upstream call lock (serialize the single request/response stdio pipe) — pre-created so
        # it is never assigned *after* first use. A separate lock guards session CREATION: the MCP
        # server dispatches requests concurrently (tg.start_soon), so two first-calls to the same
        # upstream could otherwise both open a session and leak/duplicate the subprocess.
        self._locks = {name: asyncio.Lock() for name in self._specs}
        self._create_lock = asyncio.Lock()

    @classmethod
    def from_config(
        cls, upstreams: Sequence[Mapping[str, Any]], *, timeout: float = 30.0
    ) -> McpUpstreamClient:
        return cls([UpstreamSpec.from_config(u) for u in upstreams], timeout=timeout)

    def upstream_names(self) -> list[str]:
        return list(self._specs)

    async def _session_for(self, name: str) -> ClientSession:
        existing = self._sessions.get(name)
        if existing is not None:
            return existing
        async with self._create_lock:  # double-checked: only one coroutine opens a given upstream
            cached = self._sessions.get(name)
            if cached is not None:
                return cached
            spec = self._specs[name]
            read, write = await self._stack.enter_async_context(stdio_client(spec.stdio_params()))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await asyncio.wait_for(session.initialize(), self._timeout)
            self._sessions[name] = session
            _log.info("upstream session opened", extra={"upstream": name})
            return session

    async def list_tools(self, name: str) -> list[types.Tool]:
        """List the tools a registered upstream exposes (used to build the proxy's tool surface)."""
        session = await self._session_for(name)
        async with self._locks[name]:
            result = await asyncio.wait_for(session.list_tools(), self._timeout)
        return list(result.tools)

    async def forward(self, call: ToolCall) -> ToolResult:
        """Forward an approved call to its upstream. Never raises — failures become ok=False."""
        if call.upstream not in self._specs:
            return self._failure(call, f"unknown upstream {call.upstream!r}")
        try:
            session = await self._session_for(call.upstream)
            async with self._locks[call.upstream]:
                raw = await asyncio.wait_for(
                    session.call_tool(call.tool, call.arguments), self._timeout
                )
        except Exception as exc:  # noqa: BLE001 — fail-closed: convert any failure, never hang
            _log.error(
                "upstream forward failed",
                extra={"call_id": call.call_id, "upstream": call.upstream, "tool": call.tool},
            )
            return self._failure(call, f"{type(exc).__name__}: {exc}")
        return ToolResult(
            call_id=call.call_id, ok=not raw.isError, summary=_summarize(raw), raw=raw
        )

    @staticmethod
    def _failure(call: ToolCall, reason: str) -> ToolResult:
        raw = types.CallToolResult(
            content=[types.TextContent(type="text", text=reason)], isError=True
        )
        return ToolResult(call_id=call.call_id, ok=False, summary=f"error: {reason}", raw=raw)

    async def aclose(self) -> None:
        """Close every open upstream session (called on gateway shutdown)."""
        await self._stack.aclose()
        self._sessions.clear()
        self._locks.clear()
