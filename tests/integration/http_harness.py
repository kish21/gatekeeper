"""Shared live-HTTP test harness — ONE copy of the uvicorn/MCP-client plumbing.

Used by test_http_transport.py (static-token runtime) and test_oidc_http.py (OIDC runtime): the
tests differ only in how the runtime is built; serving it on a real ephemeral-port uvicorn and
driving it with the official MCP client is identical and lives here.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from gatekeeper.gateway.factory import GatewayRuntime
from gatekeeper.transport.http_server import create_app
from gatekeeper.transport.surface import build_tool_index


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def text(result: types.CallToolResult) -> str:
    return "".join(b.text for b in result.content if isinstance(b, types.TextContent))


@asynccontextmanager
async def serving(runtime: GatewayRuntime) -> AsyncIterator[str]:
    """Run the real governed app under real uvicorn on an ephemeral loopback port."""
    try:
        index = await build_tool_index(runtime)
        app = create_app(runtime, index, path="/mcp")
        port = free_port()
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False)
        )
        task = asyncio.create_task(server.serve())
        try:
            async with asyncio.timeout(30):
                # uvicorn exposes no readiness Event — polling `started` is its documented
                # pattern; the timeout above bounds it.
                while not server.started:  # noqa: ASYNC110
                    await asyncio.sleep(0.02)
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            async with asyncio.timeout(30):
                await task
    finally:
        await runtime.aclose()


@asynccontextmanager
async def client(base: str, token: str | None) -> AsyncIterator[ClientSession]:
    """An initialized MCP client session against the harness gateway (None = no Authorization)."""
    headers = {"Authorization": f"Bearer {token}"} if token is not None else None
    async with streamablehttp_client(f"{base}/mcp", headers=headers) as (read, write, _sid):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session
