"""CLI tests for ``gatekeeper seed-demo`` — the non-destructive demo-prep helper.

Runs against the repo's committed ``config/`` (so it also asserts that config parses) but redirects
the demo sandbox to a temp dir via ``DEMO_FILE_ROOT``. Asserts: exit 0, the sandbox + sample file
are created, the recipe + governed config are shown, it is idempotent, and — critically — no bearer
token ever leaks into the output (only principal + role are shown).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from gatekeeper.cli import app as cli_app

runner = CliRunner()

# A real dev token from config/identities.yaml — must NEVER appear in seed-demo output.
SECRET_TOKEN = "dev-token-alice-REPLACE-ME"


def test_seed_demo_prepares_sandbox_and_prints_recipe(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv(cli_app._DEMO_SANDBOX_ENV, str(tmp_path / "sandbox"))
    result = runner.invoke(cli_app.app, ["seed-demo"])
    assert result.exit_code == 0, result.output

    # Sandbox + sample file created so a governed read works immediately.
    sample = tmp_path / "sandbox" / cli_app._DEMO_SAMPLE_FILE
    assert sample.is_file()
    assert "GateKeeperAI" in sample.read_text(encoding="utf-8")

    # Shows what is governed (both upstreams from config) + the run recipe.
    assert "demo-files" in result.output
    assert "time" in result.output  # the real third-party server registered in config
    assert "make serve" in result.output
    assert "GATEKEEPER_HMAC_KEY" in result.output
    # The literal extra name must survive Rich rendering (not be eaten as a [markup] tag).
    assert ".[demo]" in result.output


def test_seed_demo_shows_roles_but_never_leaks_tokens(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv(cli_app._DEMO_SANDBOX_ENV, str(tmp_path / "sandbox"))
    result = runner.invoke(cli_app.app, ["seed-demo"])
    assert result.exit_code == 0
    # Principals + roles are shown; the secret bearer token is not.
    assert "alice" in result.output and "operator" in result.output
    assert SECRET_TOKEN not in result.output


def test_seed_demo_is_idempotent(tmp_path: Any, monkeypatch: Any) -> None:
    sandbox = tmp_path / "sandbox"
    monkeypatch.setenv(cli_app._DEMO_SANDBOX_ENV, str(sandbox))
    # Pre-seed the sample with custom content; a second run must not clobber it.
    sandbox.mkdir(parents=True)
    sample = sandbox / cli_app._DEMO_SAMPLE_FILE
    sample.write_text("user-edited-do-not-overwrite", encoding="utf-8")

    result = runner.invoke(cli_app.app, ["seed-demo"])
    assert result.exit_code == 0
    assert sample.read_text(encoding="utf-8") == "user-edited-do-not-overwrite"


def test_seed_demo_fails_loud_on_missing_config(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv(cli_app._DEMO_SANDBOX_ENV, str(tmp_path / "sandbox"))
    monkeypatch.setenv("GATEKEEPER_CONFIG_DIR", str(tmp_path / "does-not-exist"))
    result = runner.invoke(cli_app.app, ["seed-demo"])
    assert result.exit_code == 2  # fail-loud, not a silent default


def test_seed_demo_output_is_legacy_windows_console_safe(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv(cli_app._DEMO_SANDBOX_ENV, str(tmp_path / "sandbox"))
    result = runner.invoke(cli_app.app, ["seed-demo"])
    assert result.exit_code == 0
    # Pure ASCII: box.ASCII borders + no smart punctuation (em-dash etc.) that a legacy console
    # renders as a replacement char. Stricter than cp1252 (which would accept an em-dash).
    result.output.encode("ascii")


def test_seed_demo_sandbox_path_matches_demo_server_default() -> None:
    # Guard against drift: the CLI's sandbox default must mirror examples/demo_file_server.py.
    server_src = Path("examples/demo_file_server.py").read_text(encoding="utf-8")
    assert f'"{cli_app._DEMO_SANDBOX_DEFAULT}"' in server_src
    assert f'"{cli_app._DEMO_SANDBOX_ENV}"' in server_src
