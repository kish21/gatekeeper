"""Shared proxy surface — ONE builder for the governed MCP server, used by every transport.

stdio (M1) and Streamable HTTP (M3.1) are two inbound bindings of the *same* low-level MCP
``Server``. The tool index and the list/call handlers are built here exactly once so governance
behavior cannot drift between transports: both route every call through ``GatewayPipeline``
(identity -> classify -> audit-before -> forward -> audit) and relay the upstream's untouched
result.

What differs per transport is only WHERE the bearer token comes from — injected as a
``TokenProvider`` callable:
  * stdio  -> the process-level ``$GATEKEEPER_AGENT_TOKEN`` (one principal per process).
  * HTTP   -> the per-request ``Authorization: Bearer`` header (multi-principal, ADR-008).

Fail-closed surface (ADR-008): ``tools/list`` resolves the caller's token before returning
anything, so an unauthenticated client cannot enumerate tools (it gets an EMPTY list, see the
handler note); a ``tools/call`` with a bad token still reaches the pipeline, which RECORDS the
identity-deny in the ledger and then refuses — never a silent transport-level rejection.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import mcp.types as types
from mcp.server.lowlevel import Server

from gatekeeper.domain.errors import IdentityError, PolicyDenied
from gatekeeper.gateway.factory import GatewayRuntime
from gatekeeper.infra.logging import get_logger

SERVER_NAME = "gatekeeper"

#: Returns the bearer token for the CURRENT call ("" when absent — the resolver then fails closed).
TokenProvider = Callable[[], str]


async def build_tool_index(runtime: GatewayRuntime) -> dict[str, tuple[str, types.Tool]]:
    """Map each upstream tool name -> (upstream, Tool). First wins on a cross-upstream collision.

    Resilient to a single bad upstream (M1.4): since any MCP server is registered purely by
    config, one that fails to launch or list its tools (missing package, wrong command,
    unreachable) must NOT take down governance for the healthy ones. Such an upstream is logged and
    SKIPPED - its tools are simply not exposed, so no call to it is possible (no ungoverned
    bypass); every other upstream stays governed. The `gateway ready` log lists the tools actually
    exposed, so a skipped upstream is visible.
    """
    logger = get_logger("gatekeeper.transport")
    index: dict[str, tuple[str, types.Tool]] = {}
    for upstream in runtime.upstream.upstream_names():
        try:
            tools = await runtime.upstream.list_tools(upstream)
        except Exception as exc:  # noqa: BLE001 — isolate a bad upstream; never crash the gateway
            logger.error(
                "upstream unavailable; skipping (its tools will not be exposed)",
                extra={"upstream": upstream, "error": f"{type(exc).__name__}: {exc}"},
            )
            continue
        for tool in tools:
            if tool.name in index:
                logger.warning(
                    "tool name collision; keeping first",
                    extra={"tool": tool.name, "kept": index[tool.name][0], "skipped": upstream},
                )
                continue
            index[tool.name] = (upstream, tool)
    return index


def build_proxy_server(
    runtime: GatewayRuntime,
    index: dict[str, tuple[str, types.Tool]],
    token_provider: TokenProvider,
) -> Server[object, object]:
    """Create the governed low-level MCP server wired to the pipeline (transport-agnostic)."""
    server: Server[object, object] = Server(SERVER_NAME)
    log = get_logger("gatekeeper.transport")

    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def _list_tools() -> list[types.Tool]:
        # Fail-closed enumeration (ADR-008): an unauthenticated caller learns NOTHING about the
        # governed surface — it gets an empty list. Returning [] instead of raising is
        # load-bearing: the SDK's call_tool wrapper refreshes its tool cache through THIS handler,
        # so a raise here would short-circuit an unauthenticated tools/call before the pipeline
        # could ledger the identity-deny (which would break "every call accounted for").
        try:
            runtime.identity.resolve(token_provider())
        except IdentityError:
            log.warning("tools/list denied: unauthenticated caller (returning empty list)")
            return []
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
                token=token_provider(),
                upstream=upstream,
                tool=name,
                arguments=arguments,
                call_id=call_id,
            )
        except (IdentityError, PolicyDenied) as exc:
            # Authn failure OR RBAC deny — both surface to the agent as an error; the call was
            # already recorded by the pipeline and was never forwarded (fail-closed).
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"denied: {exc}")], isError=True
            )
        if isinstance(result.raw, types.CallToolResult):
            return result.raw  # transparent relay of the upstream's untouched result
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=result.summary)], isError=not result.ok
        )

    return server
