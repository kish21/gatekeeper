"""stdio MCP transport — the transparent governed proxy a local agent connects to.

One inbound binding of the shared proxy surface (``transport.surface`` — the tool index and the
governed list/call handlers are built there, identically for stdio and HTTP, so governance cannot
drift between transports). This module only owns what is stdio-specific:

Identity for the stdio session: the agent presents one bearer token (``$GATEKEEPER_AGENT_TOKEN``),
resolved at startup (fail-fast: refuse an unauthenticated agent) and re-checked per call by the
pipeline. Per-request tokens (multi-principal) are the HTTP transport's model (ADR-008).
"""

from __future__ import annotations

from mcp.server.stdio import stdio_server

from gatekeeper.config.loader import get_settings
from gatekeeper.gateway.factory import build_runtime
from gatekeeper.infra.logging import configure_logging, get_logger
from gatekeeper.transport.surface import build_proxy_server, build_tool_index


async def serve_stdio() -> None:
    """Boot the runtime, authenticate the agent, build the proxy surface, and serve over stdio."""
    configure_logging(get_settings().log_level)
    log = get_logger("gatekeeper.transport")

    runtime = build_runtime()  # fail-closed HMAC key + fail-loud (ledger table must exist)
    token = get_settings().agent_token
    principal = runtime.identity.resolve(token)  # fail-fast: refuse an unauthenticated agent

    try:
        index = await build_tool_index(runtime)
        log.info(
            "gateway ready",
            extra={
                "transport": "stdio",
                "principal": principal.id,
                "upstreams": runtime.upstream.upstream_names(),
                "tools": sorted(index),
            },
        )
        server = build_proxy_server(runtime, index, lambda: token)
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await runtime.aclose()
