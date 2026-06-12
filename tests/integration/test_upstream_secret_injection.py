"""Integration — a ``{from_env}`` upstream secret actually reaches the launched server subprocess.

Proves the end of the chain the unit tests stop at: a credential declared as ``{from_env: NAME}`` in
config is resolved from the environment and handed to the REAL upstream subprocess. We point the
demo server's sandbox-root env var at a temp dir via ``{from_env}``; reading a file placed there
only succeeds if the resolved value was injected into the child process's environment.
"""

from __future__ import annotations

import sys
import uuid
from typing import Any

from mcp import types

from gatekeeper.adapters.upstream.mcp_client import McpUpstreamClient, UpstreamSpec
from gatekeeper.schemas.models import ToolCall


async def test_from_env_secret_reaches_subprocess(tmp_path: Any) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "proof.txt").write_text("resolved-into-the-child", encoding="utf-8")

    # DEMO_FILE_ROOT is declared as a secret reference; its value lives ONLY in the injected source,
    # not in the config dict - exactly how a real GitHub token would be referenced.
    spec = UpstreamSpec.from_config(
        {
            "name": "demo-files",
            "transport": "stdio",
            "command": [sys.executable, "-m", "examples.demo_file_server"],
            "env": {"DEMO_FILE_ROOT": {"from_env": "GK_SANDBOX_ROOT"}},
        },
        secret_source={"GK_SANDBOX_ROOT": str(sandbox)},
    )
    assert spec.env == {"DEMO_FILE_ROOT": str(sandbox)}  # resolved before launch

    client = McpUpstreamClient([spec], timeout=30.0)
    try:
        result = await client.forward(
            ToolCall(
                call_id=uuid.uuid4().hex,
                upstream="demo-files",
                tool="read_file",
                arguments={"path": "proof.txt"},
            )
        )
        # The child read the file from OUR temp sandbox -> it received the resolved DEMO_FILE_ROOT.
        assert result.ok
        assert isinstance(result.raw, types.CallToolResult)
        relayed = "".join(b.text for b in result.raw.content if isinstance(b, types.TextContent))
        assert "resolved-into-the-child" in relayed
    finally:
        await client.aclose()
