"""CLI — ``gatekeeper init`` and ``gatekeeper doctor``: the whole first run in two commands.

``init`` must turn a fresh checkout into a runnable gateway with no manual secret handling, and be
safe to re-run. ``doctor`` must say what is wrong in plain terms and print the exact MCP host
config to paste, with absolute paths (so the host can launch the gateway from anywhere).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gatekeeper.cli import app as cli_app
from gatekeeper.config import loader

runner = CliRunner()
REPO = Path(".").resolve()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway copy of the repo's config + policies, with no .env and no ledger."""
    root = tmp_path / "proj"
    shutil.copytree(REPO / "config", root / "config")
    shutil.copytree(REPO / "policies", root / "policies")
    monkeypatch.setenv("GATEKEEPER_CONFIG_DIR", str(root / "config"))
    monkeypatch.setenv(cli_app._DEMO_SANDBOX_ENV, str(root / "sandbox"))
    for var in ("GATEKEEPER_HMAC_KEY", "GATEKEEPER_AGENT_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)  # deliberately NOT the project root
    loader.get_settings.cache_clear()
    return root


def test_init_writes_secrets_creates_ledger_and_seeds_demo(project: Path) -> None:
    result = runner.invoke(cli_app.app, ["init"])
    assert result.exit_code == 0, result.output

    env = cli_app._read_env_file(project / ".env")
    assert len(env["GATEKEEPER_HMAC_KEY"]) == 64  # generated, strong
    assert env["GATEKEEPER_AGENT_TOKEN"] == "dev-token-alice-REPLACE-ME"  # first operator
    assert (project / ".gatekeeper" / "audit.db").is_file()  # ledger created, no migrate step
    assert (project / "sandbox" / cli_app._DEMO_SAMPLE_FILE).is_file()
    assert "gatekeeper doctor" in result.output  # tells the user the next step
    assert env["GATEKEEPER_HMAC_KEY"] not in result.output  # never prints the secret


def test_init_is_idempotent_and_keeps_user_values(project: Path) -> None:
    (project / ".env").write_text("GATEKEEPER_HMAC_KEY=" + "u" * 64 + "\n", encoding="utf-8")
    assert runner.invoke(cli_app.app, ["init"]).exit_code == 0
    first = cli_app._read_env_file(project / ".env")
    assert first["GATEKEEPER_HMAC_KEY"] == "u" * 64  # user's key kept
    assert runner.invoke(cli_app.app, ["init"]).exit_code == 0
    assert cli_app._read_env_file(project / ".env") == first  # second run changes nothing


def test_init_fails_loud_without_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEKEEPER_CONFIG_DIR", str(tmp_path / "nope"))
    loader.get_settings.cache_clear()
    assert runner.invoke(cli_app.app, ["init"]).exit_code == 2


def test_doctor_passes_after_init_and_prints_host_config(project: Path) -> None:
    assert runner.invoke(cli_app.app, ["init"]).exit_code == 0
    loader.get_settings.cache_clear()
    result = runner.invoke(cli_app.app, ["doctor"])
    assert result.exit_code == 0, result.output
    for check in ("HMAC key", "audit ledger", "policy", "agent token", "server: demo-files"):
        assert check in result.output
    assert "FAIL" not in result.output

    block = json.loads(result.stdout[result.stdout.index("{") :])
    server = block["mcpServers"]["gatekeeper"]
    assert Path(server["command"]).is_absolute()
    assert server["args"] == ["serve"]
    assert server["env"]["GATEKEEPER_CONFIG_DIR"] == str((project / "config").resolve())


def test_doctor_json_only(project: Path) -> None:
    assert runner.invoke(cli_app.app, ["init"]).exit_code == 0
    loader.get_settings.cache_clear()
    result = runner.invoke(cli_app.app, ["doctor", "--json"])
    assert result.exit_code == 0
    assert set(json.loads(result.stdout)) == {"mcpServers"}


def test_doctor_names_the_missing_pieces(project: Path) -> None:
    # No init: no key, no token -> exit 1 with a FAIL row per problem, never a traceback.
    result = runner.invoke(cli_app.app, ["doctor"])
    assert result.exit_code == 1, result.output
    assert "FAIL" in result.output
    assert "HMAC key" in result.output and "gatekeeper init" in result.output
    assert "Traceback" not in result.output


def test_doctor_flags_a_server_that_cannot_launch(project: Path) -> None:
    assert runner.invoke(cli_app.app, ["init"]).exit_code == 0
    (project / "config" / "upstreams.yaml").write_text(
        "upstreams:\n  - name: ghost\n    transport: stdio\n    command: [no-such-binary-xyz]\n",
        encoding="utf-8",
    )
    loader.get_settings.cache_clear()
    result = runner.invoke(cli_app.app, ["doctor"])
    assert result.exit_code == 1
    assert "server: ghost" in result.output and "not on PATH" in result.output


def test_health_boots_after_init(project: Path) -> None:
    assert runner.invoke(cli_app.app, ["init"]).exit_code == 0
    loader.get_settings.cache_clear()
    result = runner.invoke(cli_app.app, ["health"])
    assert result.exit_code == 0 and "audit ledger" in result.output


def test_doctor_output_is_legacy_windows_console_safe(project: Path) -> None:
    assert runner.invoke(cli_app.app, ["init"]).exit_code == 0
    loader.get_settings.cache_clear()
    result = runner.invoke(cli_app.app, ["doctor"])
    result.output.encode("cp1252")  # box.ASCII + no smart punctuation


def test_verify_expect_head_flag(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert runner.invoke(cli_app.app, ["init"]).exit_code == 0
    loader.get_settings.cache_clear()
    first = runner.invoke(cli_app.app, ["verify"])
    assert first.exit_code == 0
    head = first.output.split("head:")[1].split()[0]
    assert runner.invoke(cli_app.app, ["verify", "--expect-head", head]).exit_code == 0
    stale = runner.invoke(cli_app.app, ["verify", "--expect-head", "f" * 64])
    assert stale.exit_code == 1 and "TAMPERED" in stale.output


def test_serve_without_token_says_how_to_fix(project: Path) -> None:
    assert runner.invoke(cli_app.app, ["init"]).exit_code == 0
    (project / ".env").write_text(
        "GATEKEEPER_HMAC_KEY=" + "u" * 64 + "\nGATEKEEPER_AGENT_TOKEN=not-a-real-token\n",
        encoding="utf-8",
    )
    loader.get_settings.cache_clear()
    result = runner.invoke(cli_app.app, ["serve"])
    assert result.exit_code == 2
    assert "GATEKEEPER_AGENT_TOKEN" in result.stderr  # names the variable to fix


def test_seed_demo_still_works_as_hidden_alias(project: Path) -> None:
    result = runner.invoke(cli_app.app, ["seed-demo"])
    assert result.exit_code == 0, result.output
    assert (project / "sandbox" / cli_app._DEMO_SAMPLE_FILE).is_file()
    assert "gatekeeper init" in result.output


def test_first_run_test_env_is_isolated(project: Path, tmp_path: Path) -> None:
    # Guard for this test module itself: nothing above may touch the real repo's .env or ledger.
    assert not (tmp_path / ".env").exists()
    assert (project / "config").is_dir()
