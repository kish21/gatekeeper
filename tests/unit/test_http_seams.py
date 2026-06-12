"""Unit tests — HTTP transport seams (M3.1): exposure guard, bearer extraction, config knobs.

The guard is ADR-009 (fail-closed network exposure), extraction is ADR-008 (transport extracts,
pipeline decides). Both are pure seams, testable without a socket.
"""

from __future__ import annotations

import types as pytypes
from typing import Any

import pytest
from mcp.server.lowlevel.server import request_ctx
from typer.testing import CliRunner

from gatekeeper.cli import app as cli_app
from gatekeeper.config.loader import ConfigError
from gatekeeper.transport.http_server import (
    ensure_exposure_acked,
    extract_bearer_token,
    http_transport_config,
)

runner = CliRunner()


# --- ADR-009: loopback-by-default, refuse non-loopback without explicit ack -------------------
@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.53"])
def test_loopback_hosts_need_no_ack(host: str) -> None:
    ensure_exposure_acked(host, allow_non_loopback=False)  # must not raise


@pytest.mark.parametrize("host", ["0.0.0.0", "10.1.2.3", "192.168.1.5", "example.com", ""])
def test_non_loopback_refuses_boot_without_ack(host: str) -> None:
    # Includes a bare hostname: we refuse rather than resolve-and-guess (fail-closed).
    with pytest.raises(ConfigError, match="not a loopback"):
        ensure_exposure_acked(host, allow_non_loopback=False)


def test_non_loopback_allowed_with_explicit_ack() -> None:
    ensure_exposure_acked("0.0.0.0", allow_non_loopback=True)  # deliberate exposure: no raise


# --- ADR-008: bearer extraction (transport-only; "" makes the resolver fail closed) -----------
def _with_request(headers: dict[str, str]) -> Any:
    request = pytypes.SimpleNamespace(headers=headers)
    return pytypes.SimpleNamespace(request=request)


@pytest.mark.parametrize(
    ("auth", "expected"),
    [
        ("Bearer tok-123", "tok-123"),
        ("bearer tok-123", "tok-123"),  # scheme is case-insensitive
        ("Bearer   tok-123  ", "tok-123"),
        ("Basic dXNlcg==", ""),  # wrong scheme -> no token -> fail-closed downstream
        ("", ""),
        ("Bearer", ""),  # scheme without a value
    ],
)
def test_extract_bearer_token_parses_authorization(auth: str, expected: str) -> None:
    token = request_ctx.set(_with_request({"authorization": auth} if auth else {}))
    try:
        assert extract_bearer_token() == expected
    finally:
        request_ctx.reset(token)


def test_extract_bearer_token_outside_a_request_is_empty() -> None:
    assert extract_bearer_token() == ""  # no request context -> "" -> resolver fails closed


def test_extract_bearer_token_without_attached_request_is_empty() -> None:
    token = request_ctx.set(pytypes.SimpleNamespace(request=None))  # e.g. a stdio-style context
    try:
        assert extract_bearer_token() == ""
    finally:
        request_ctx.reset(token)


# --- Config knobs flow (no dead config, defaults applied) -------------------------------------
def test_http_transport_config_defaults_and_overrides() -> None:
    defaults = http_transport_config({"platform": {}})
    assert defaults == {
        "host": "127.0.0.1",
        "port": 8765,
        "path": "/mcp",
        "allow_non_loopback": False,
        "allowed_origins": [],
        "allowed_hosts": [],
    }
    cfg = http_transport_config(
        {
            "platform": {
                "transport": {
                    "http_host": "0.0.0.0",
                    "http_port": 9001,
                    "http_path": "/gateway",
                    "http_allow_non_loopback": True,
                    "http_allowed_origins": ["https://ops.example"],
                    "http_allowed_hosts": ["gw.example.com:*"],
                }
            }
        }
    )
    assert cfg == {
        "host": "0.0.0.0",
        "port": 9001,
        "path": "/gateway",
        "allow_non_loopback": True,
        "allowed_origins": ["https://ops.example"],
        "allowed_hosts": ["gw.example.com:*"],
    }


# --- CLI: unknown transport is a fail-loud misconfig, reported on stderr ----------------------
def test_serve_unknown_transport_fails_loud(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("GATEKEEPER_CONFIG_DIR", str(tmp_path))  # empty dir: defaults apply
    result = runner.invoke(cli_app.app, ["serve", "--transport", "carrier-pigeon"])
    assert result.exit_code == 2
    assert "unknown transport" in result.stderr
