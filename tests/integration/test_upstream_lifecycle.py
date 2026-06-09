"""Regression — a session opened in a CHILD task must close cleanly from a DIFFERENT task.

The low-level MCP server dispatches every call via ``tg.start_soon`` (a child task), so an upstream
whose session is first opened during a ``forward`` is opened in that child task — while the
gateway's ``aclose()`` runs later in ``serve_stdio``'s own task. When both ends of the anyio-backed
``stdio_client`` + ``ClientSession`` contexts shared one ``AsyncExitStack``, exiting them from the
other task tripped anyio's ownership check:

    RuntimeError: Attempted to exit cancel scope in a different task than it was entered in

Each upstream session now owns a dedicated lifecycle task that both opens and closes its contexts,
so shutdown is correct regardless of which task first opened the session. This test pins that
behaviour: open a session inside a child task, then ``aclose()`` from the parent task — no error.
"""

from __future__ import annotations

import sys
import uuid

import anyio

from gatekeeper.adapters.upstream.mcp_client import McpUpstreamClient, UpstreamSpec
from gatekeeper.schemas.models import ToolCall


def _demo_spec() -> UpstreamSpec:
    return UpstreamSpec(
        name="demo-files",
        transport="stdio",
        command=(sys.executable, "-m", "examples.demo_file_server"),
    )


async def test_session_opened_in_child_task_closes_without_runtimeerror() -> None:
    upstream = McpUpstreamClient([_demo_spec()], timeout=30.0)
    forwarded: list[str] = []

    async def _forward_in_child() -> None:
        # Mirrors a forward dispatched by the MCP server via tg.start_soon: this is the FIRST touch
        # of the upstream, so the persistent session is opened here, inside a child task — not in
        # the task that will later call aclose().
        result = await upstream.forward(
            ToolCall(
                call_id=uuid.uuid4().hex,
                upstream="demo-files",
                tool="list_dir",
                arguments={"path": "."},
            )
        )
        forwarded.append(result.call_id)

    async with anyio.create_task_group() as tg:
        tg.start_soon(_forward_in_child)
    # The child task has finished; its forward really ran (so the session was opened in it).
    assert len(forwarded) == 1

    # aclose() runs in THIS task — a different task than the child that opened the session. With
    # the old shared AsyncExitStack this raised the cross-task cancel-scope RuntimeError; not now.
    await upstream.aclose()  # must not raise


async def test_aclose_is_idempotent_after_child_task_open() -> None:
    # Shutdown may be reached twice (e.g. nested finally / re-entrancy); the second call is a no-op
    # and must stay quiet — runners are cleared on the first close.
    upstream = McpUpstreamClient([_demo_spec()], timeout=30.0)

    async def _open_in_child() -> None:
        await upstream.list_tools("demo-files")

    async with anyio.create_task_group() as tg:
        tg.start_soon(_open_in_child)

    await upstream.aclose()
    await upstream.aclose()  # second close: no runners left, no error
