"""Foundation tests: config flows, the startup guard is fail-closed, and the health path runs.

These also give CI a real green suite from day one.
"""

from __future__ import annotations

import pytest
from tests.conftest import GOOD_HMAC
from typer.testing import CliRunner

from gatekeeper.cli.app import app
from gatekeeper.config.loader import ConfigError, Settings, load_config, validate_security

runner = CliRunner()


# --- config actually flows (no dead config) --------------------------------
def test_config_loads_and_values_flow():
    cfg = load_config(Settings(hmac_key=GOOD_HMAC))
    assert cfg["platform"]["adapters"]["policy"] == "cedar"  # platform.yaml flowed
    assert cfg["platform"]["ledger"]["hash_algo"] == "hmac-sha256"  # the wedge knob flowed
    assert len(cfg["upstreams"]) >= 1  # registry flowed
    assert any(p["role"] == "admin" for p in cfg["identities"])  # identities flowed


# --- startup guard is FAIL-CLOSED ------------------------------------------
@pytest.mark.parametrize("bad", ["", "changeme", "example-hmac-key-do-not-use", "abc123"])
def test_guard_refuses_weak_or_short_hmac_key(bad: str):
    with pytest.raises(ConfigError):
        validate_security(Settings(hmac_key=bad))


def test_guard_accepts_strong_hmac_key():
    validate_security(Settings(hmac_key=GOOD_HMAC))  # must not raise


# --- the health path runs end-to-end ---------------------------------------
def test_health_ok_with_valid_key(monkeypatch):
    monkeypatch.setenv("GATEKEEPER_HMAC_KEY", GOOD_HMAC)
    result = runner.invoke(app, ["health"])
    assert result.exit_code == 0, result.output
    assert "ledger path" in result.output  # config was read back and shown


def test_health_fails_closed_without_key(monkeypatch):
    monkeypatch.setenv("GATEKEEPER_HMAC_KEY", "")
    result = runner.invoke(app, ["health"])
    assert result.exit_code == 2  # fail-loud, non-zero
    assert "cannot boot" in result.output


def test_health_output_is_legacy_windows_console_safe(monkeypatch):
    # Regression: the health table once used ✓/✗/— glyphs that crash a cp1252 console.
    monkeypatch.setenv("GATEKEEPER_HMAC_KEY", GOOD_HMAC)
    result = runner.invoke(app, ["health"])
    assert result.exit_code == 0
    result.output.encode("cp1252")  # must not raise UnicodeEncodeError
