"""Unit — runtime configuration comes from the environment, and paths follow the project root.

A hosted deployment must never have to bake its hostname, ledger path, or identity settings into
an image: every such knob is a ``GATEKEEPER_*`` variable. And an MCP host that launches the
gateway from an arbitrary directory must still find the ledger, the policies, and ``.env``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from gatekeeper.config import loader
from gatekeeper.config.loader import ConfigError, Settings, load_config

REPO_CONFIG = Path("config").resolve()


def _settings(**overrides: Any) -> Settings:
    return Settings(config_dir=REPO_CONFIG, **overrides)


def test_transport_knobs_override_yaml() -> None:
    cfg = load_config(
        _settings(
            transport="http",
            http_host="0.0.0.0",
            http_port=9999,
            http_allow_non_loopback=True,
            http_allowed_hosts="gw.example.com, other.example.org",
            http_allowed_origins="https://ops.example",
        )
    )
    transport = cfg["platform"]["transport"]
    assert transport["mode"] == "http"
    assert transport["http_host"] == "0.0.0.0"
    assert transport["http_port"] == 9999
    assert transport["http_allow_non_loopback"] is True
    assert transport["http_allowed_hosts"][-2:] == ["gw.example.com", "other.example.org"]
    assert transport["http_allowed_origins"][-1] == "https://ops.example"


def test_yaml_values_survive_when_env_is_empty() -> None:
    cfg = load_config(_settings())
    assert cfg["platform"]["transport"]["mode"] == "stdio"  # repo default, untouched


def test_platform_hostname_is_trusted_automatically(monkeypatch: pytest.MonkeyPatch) -> None:
    # Azure Container Apps injects the app's public FQDN; the gateway allow-lists it itself so a
    # hosted deploy never needs a second build to learn its own name.
    monkeypatch.setenv("CONTAINER_APP_HOSTNAME", "gk.azurecontainerapps.io")
    cfg = load_config(_settings())
    assert "gk.azurecontainerapps.io" in cfg["platform"]["transport"]["http_allowed_hosts"]


def test_identity_and_oidc_come_from_env() -> None:
    cfg = load_config(
        _settings(
            identity="oidc",
            oidc_issuer="https://login.example/tenant/v2.0",
            oidc_audience="api://gatekeeper",
            oidc_group_role_map="g-ops=operator, g-view=readonly",
        )
    )
    platform = cfg["platform"]
    assert platform["adapters"]["identity"] == "oidc"
    oidc = platform["identity"]["oidc"]
    assert oidc["issuer"] == "https://login.example/tenant/v2.0"
    assert oidc["audience"] == "api://gatekeeper"
    assert oidc["group_role_map"] == {"g-ops": "operator", "g-view": "readonly"}


def test_malformed_group_role_map_fails_loud() -> None:
    with pytest.raises(ConfigError, match="GATEKEEPER_OIDC_GROUP_ROLE_MAP"):
        load_config(_settings(oidc_group_role_map="no-equals-sign"))


def test_ledger_and_policy_paths_resolve_against_project_root(tmp_path: Path) -> None:
    # A config dir anywhere; relative paths inside it resolve against ITS parent, not the cwd.
    project = tmp_path / "proj"
    (project / "config").mkdir(parents=True)
    (project / "config" / "platform.yaml").write_text(
        "ledger:\n  path: ./data/audit.db\npolicy:\n  dir: ./rules\n", encoding="utf-8"
    )
    cfg = load_config(Settings(config_dir=project / "config"))
    assert cfg["platform"]["ledger"]["path"] == str(project / "data" / "audit.db")
    assert cfg["platform"]["policy"]["dir"] == str(project / "rules")


def test_env_ledger_path_override_wins(tmp_path: Path) -> None:
    cfg = load_config(_settings(ledger_path=str(tmp_path / "elsewhere.db")))
    assert cfg["platform"]["ledger"]["path"] == str(tmp_path / "elsewhere.db")


def test_dotenv_is_read_from_the_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    (project / "config").mkdir(parents=True)
    (project / ".env").write_text("GATEKEEPER_HMAC_KEY=" + "r" * 64 + "\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)  # cwd has NO .env
    monkeypatch.setenv("GATEKEEPER_CONFIG_DIR", str(project / "config"))
    monkeypatch.delenv("GATEKEEPER_HMAC_KEY", raising=False)
    loader.get_settings.cache_clear()
    assert loader.get_settings().hmac_key == "r" * 64
    assert loader.env_file_path(loader.get_settings()) == project / ".env"


def test_placeholder_token_detection() -> None:
    assert loader.has_placeholder_tokens([{"token": "dev-token-alice-REPLACE-ME"}])
    assert not loader.has_placeholder_tokens([{"token": "8f3a" * 8}])


def test_identities_can_come_from_the_environment() -> None:
    cfg = load_config(_settings(identities="ops:operator:tok-1; viewer:readonly:tok-2"))
    assert cfg["identities"] == [
        {"principal": "ops", "role": "operator", "token": "tok-1"},
        {"principal": "viewer", "role": "readonly", "token": "tok-2"},
    ]
    assert not loader.has_placeholder_tokens(cfg["identities"])


def test_malformed_identities_fail_loud() -> None:
    with pytest.raises(ConfigError, match="GATEKEEPER_IDENTITIES"):
        load_config(_settings(identities="ops:operator"))
