"""CLI test — ``gatekeeper serve`` reports a boot failure on STDERR, never stdout.

For ``serve``, stdout is the MCP JSON-RPC channel an agent host (Claude Desktop, an IDE) speaks on.
A human-readable error on stdout corrupts that channel — the host reports "... is not valid JSON"
and disconnects. A fail-closed boot error (here forced by a missing config dir) must land on
stderr, leaving stdout clean.
"""

from __future__ import annotations

from typing import Any

from typer.testing import CliRunner

from gatekeeper.cli import app as cli_app

runner = CliRunner()


def test_serve_boot_error_goes_to_stderr_not_stdout(tmp_path: Any, monkeypatch: Any) -> None:
    # Force a fast fail-closed boot error before the stdio server ever starts.
    monkeypatch.setenv("GATEKEEPER_CONFIG_DIR", str(tmp_path / "missing"))
    result = runner.invoke(cli_app.app, ["serve"])
    assert result.exit_code == 2
    assert "cannot serve" in result.stderr  # readable error on stderr
    assert "cannot serve" not in result.stdout  # stdout (the MCP channel) stays clean
