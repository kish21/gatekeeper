"""Unit — upstream env secret references (config-driven, fail-closed).

``config/upstreams.yaml`` may give an upstream a credential as ``{from_env: NAME}`` instead of a
literal, so the secret VALUE stays in ``.env`` while only its NAME appears in YAML — the project's
"secrets never live in YAML" rule (``config/loader.py``) applied to an upstream's own credentials
(e.g. a GitHub server's token). These tests pin the resolution, its backward compatibility with
literals, and its fail-closed behaviour on a missing or malformed reference.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from gatekeeper.adapters.upstream.mcp_client import McpUpstreamClient, UpstreamSpec
from gatekeeper.config import loader
from gatekeeper.config.loader import ConfigError


def _spec(env: dict[str, Any], source: Mapping[str, str]) -> UpstreamSpec:
    return UpstreamSpec.from_config(
        {"name": "github", "command": ["x"], "env": env}, secret_source=source
    )


def test_literal_env_values_pass_through_unchanged() -> None:
    # Plain scalars are never resolved, only stringified (backward compatible with old config).
    spec = _spec({"PLAIN": "value", "PORT": 8080}, {})
    assert spec.env == {"PLAIN": "value", "PORT": "8080"}


def test_from_env_reference_resolves_secret_from_source() -> None:
    spec = _spec({"GITHUB_TOKEN": {"from_env": "GH_PAT"}}, {"GH_PAT": "ghp_secret"})
    assert spec.env == {"GITHUB_TOKEN": "ghp_secret"}  # value pulled from the source, not the YAML


def test_missing_secret_fails_closed() -> None:
    # Referenced but absent: abort startup rather than launch the server without the credential.
    with pytest.raises(ConfigError, match="not set"):
        _spec({"GITHUB_TOKEN": {"from_env": "ABSENT"}}, {})


def test_malformed_reference_is_rejected() -> None:
    # A mapping that is not exactly {from_env: NAME} is a config error, never a silent literal.
    with pytest.raises(ConfigError, match="from_env"):
        _spec({"T": {"from_env": "A", "extra": "B"}}, {"A": "x"})
    with pytest.raises(ConfigError, match="from_env"):
        _spec({"T": {"wrong_key": "A"}}, {})
    with pytest.raises(ConfigError, match="from_env"):
        _spec({"T": {"from_env": ""}}, {})  # empty secret name


def test_no_env_block_is_none() -> None:
    spec = UpstreamSpec.from_config({"name": "a", "command": ["x"]}, secret_source={})
    assert spec.env is None


def test_client_from_config_threads_the_injected_source() -> None:
    # Succeeds only because the injected source supplies the secret (a name absent from the real
    # process env) - proving the source is threaded down to each per-upstream spec.
    client = McpUpstreamClient.from_config(
        [{"name": "github", "command": ["x"], "env": {"T": {"from_env": "GK_ONLY_IN_SOURCE"}}}],
        secret_source={"GK_ONLY_IN_SOURCE": "resolved"},
    )
    assert client.upstream_names() == ["github"]


def test_client_from_config_fails_closed_on_missing_secret() -> None:
    with pytest.raises(ConfigError, match="not set"):
        McpUpstreamClient.from_config(
            [{"name": "github", "command": ["x"], "env": {"T": {"from_env": "ABSENT"}}}],
            secret_source={},
        )


def test_secret_source_merges_dotenv_then_real_env(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # secret_source() is what serve passes down: .env values, overlaid by real env (exported wins).
    (tmp_path / ".env").write_text("FROM_DOTENV=a\nOVERRIDDEN=from_dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)  # secret_source reads .env relative to cwd
    monkeypatch.setenv("OVERRIDDEN", "from_real_env")
    monkeypatch.setenv("FROM_REAL_ENV", "b")

    src = loader.secret_source()

    assert src["FROM_DOTENV"] == "a"  # picked up from .env
    assert src["FROM_REAL_ENV"] == "b"  # picked up from the real environment
    assert src["OVERRIDDEN"] == "from_real_env"  # an exported var wins over .env
