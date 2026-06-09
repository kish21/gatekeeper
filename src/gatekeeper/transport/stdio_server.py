"""stdio MCP transport — the transparent governed proxy the agent connects to.

GateKeeper is an MCP **server** to the agent and (via the upstream adapter) an MCP **client** to
each real server. On startup it lists every registered upstream's tools and re-exposes them UNDER
THEIR ORIGINAL NAMES (transparent: no behavioral change vs calling the server directly). Each call
is routed through the ``GatewayPipeline`` (identity -> classify -> audit-before -> forward -> audit)
and the upstream's untouched result is relayed straight back to the agent.

Identity for the stdio session: the agent presents one bearer token (``$GATEKEEPER_AGENT_TOKEN``),
resolved at startup (fail-fast: refuse an unauthenticated agent) and re-checked per call by
the pipeline. Per-call tokens / OIDC arrive with M1.2 / the deferred identity work (ADR-006).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from gatekeeper.config.loader import get_settings
from gatekeeper.domain.errors import IdentityError
from gatekeeper.gateway.factory import GatewayRuntime, build_runtime
from gatekeeper.infra.logging import configure_logging, get_logger

_SERVER_NAME = "gatekeeper"


async def _build_tool_index(runtime: GatewayRuntime) -> dict[str, tuple[str, types.Tool]]:
    """Map each upstream tool name -> (upstream, Tool). First wins on a cross-upstream collision."""
    logger = get_logger("gatekeeper.transport")
    index: dict[str, tuple[str, types.Tool]] = {}
    for upstream in runtime.upstream.upstream_names():
        for tool in await runtime.upstream.list_tools(upstream):
            if tool.name in index:
                logger.warning(
                    "tool name collision; keeping first",
                    extra={"tool": tool.name, "kept": index[tool.name][0], "skipped": upstream},
                )
                continue
            index[tool.name] = (upstream, tool)
    return index


def _build_server(
    runtime: GatewayRuntime, token: str, index: dict[str, tuple[str, types.Tool]]
) -> Server[object, object]:
    """Create the low-level MCP server wired to the pipeline."""
    server: Server[object, object] = Server(_SERVER_NAME)

    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def _list_tools() -> list[types.Tool]:
        return [tool for (_upstream, tool) in index.values()]

    # validate_input=False: every call reaches the pipeline so it is AUDITED — even one with
    # schema-invalid arguments (the upstream still validates on forward). With the SDK default
    # (True), a malformed call is rejected before our handler and would leave no ledger entry.
    @server.call_tool(validate_input=False)  # type: ignore[untyped-decorator]
    async def _call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        routed = index.get(name)
        if routed is None:  # fail-closed: an unrouted tool is never forwarded
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"unknown tool {name!r}")],
                isError=True,
            )
        upstream, _tool = routed
        call_id = uuid4().hex
        try:
            result = await runtime.pipeline.handle(
                token=token, upstream=upstream, tool=name, arguments=arguments, call_id=call_id
            )
        except IdentityError as exc:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"denied: {exc}")], isError=True
            )
        if isinstance(result.raw, types.CallToolResult):
            return result.raw  # transparent relay of the upstream's untouched result
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=result.summary)], isError=not result.ok
        )

    return server


async def serve_stdio() -> None:
    """Boot the runtime, authenticate the agent, build the proxy surface, and serve over stdio."""
    configure_logging(get_settings().log_level)
    log = get_logger("gatekeeper.transport")

    runtime = build_runtime()  # fail-closed HMAC key + fail-loud (ledger table must exist)
    token = get_settings().agent_token
    principal = runtime.identity.resolve(token)  # fail-fast: refuse an unauthenticated agent

    try:
        index = await _build_tool_index(runtime)
        log.info(
            "gateway ready",
            extra={
                "principal": principal.id,
                "upstreams": runtime.upstream.upstream_names(),
                "tools": sorted(index),
            },
        )
        server = _build_server(runtime, token, index)
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await runtime.aclose()
