"""Unit — a stdio upstream's launcher resolves to the gateway's OWN interpreter.

A config-declared ``python -m your_server`` upstream must launch under the same interpreter the
gateway runs in, not whatever bare ``python`` the host's PATH happens to resolve to — otherwise,
under an MCP host like Claude Desktop, the subprocess would fail to import its package and the tools
would silently never appear. Any other launcher (npx, a full path) passes through unchanged.
"""

from __future__ import annotations

import sys

import pytest

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


def test_stdio_env_is_a_spawn_allowlist_never_the_whole_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A governed server gets what it needs to START (PATH, HOME, the Windows system vars) and
    # nothing else: not the gateway's secrets, not unrelated credentials in the gateway's env.
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    monkeypatch.setenv("GATEKEEPER_HMAC_KEY", "should-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-leak-either")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "nor-this")
    env = (
        UpstreamSpec(name="u", transport="stdio", command=("python", "-m", "x")).stdio_params().env
    )
    assert env is not None
    assert env["PATH"] == "/usr/bin"
    assert env["SystemRoot"] == "C:\\Windows"
    for leaked in ("GATEKEEPER_HMAC_KEY", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY"):
        assert leaked not in env


def test_stdio_configured_env_is_added_on_top(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_FILE_ROOT", "from-process")  # not a spawn var: not inherited
    spec = UpstreamSpec(
        name="u",
        transport="stdio",
        command=("python", "-m", "x"),
        env={"DEMO_FILE_ROOT": "from-config"},
    )
    assert spec.stdio_params().env["DEMO_FILE_ROOT"] == "from-config"  # declared env reaches it
