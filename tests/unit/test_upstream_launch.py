"""Unit — a stdio upstream's launcher resolves to the gateway's OWN interpreter.

A config-declared ``python -m your_server`` upstream must launch under the same interpreter the
gateway runs in, not whatever bare ``python`` the host's PATH happens to resolve to — otherwise,
under an MCP host like Claude Desktop, the subprocess would fail to import its package and the tools
would silently never appear. Any other launcher (npx, a full path) passes through unchanged.
"""

from __future__ import annotations

import sys

from gatekeeper.adapters.upstream.mcp_client import UpstreamSpec


def _params(command: tuple[str, ...]) -> object:
    return UpstreamSpec(name="u", transport="stdio", command=command).stdio_params()


def test_bare_python_launcher_pinned_to_this_interpreter() -> None:
    params = _params(("python", "-m", "examples.demo_file_server"))
    assert params.command == sys.executable
    assert params.args == ["-m", "examples.demo_file_server"]  # args untouched


def test_python3_launcher_pinned_to_this_interpreter() -> None:
    assert _params(("python3", "-m", "x")).command == sys.executable


def test_non_python_launcher_passes_through() -> None:
    params = _params(("npx", "-y", "@modelcontextprotocol/server-github"))
    assert params.command == "npx"
    assert params.args == ["-y", "@modelcontextprotocol/server-github"]
