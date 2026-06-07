"""Typed configuration loader + startup guard — the no-hardcoding engine.

Sources, highest precedence first:
  1. Environment / ``.env``      -> secrets + a few overrides (``Settings``)
  2. ``config/platform.yaml``    -> engine/technical knobs
  3. ``config/product.yaml``     -> product/business knobs
Plus deployment data: ``config/upstreams.yaml`` (registry) and ``config/identities.yaml`` (dev map).

Secrets NEVER live in YAML — only their *names* appear there; values come from ``.env``.
The startup guard (``validate_security`` / ``boot``) is **fail-loud on misconfig** and
**fail-closed on security**: the gateway refuses to boot without a real HMAC key, because that key
is what makes the audit ledger tamper-evident (ADR-003). A silent insecure boot is not an option.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised when configuration is missing, unparseable, or insecure. Boot must abort."""


class Settings(BaseSettings):
    """Secrets and environment-level overrides (read from ``.env`` / real env)."""

    model_config = SettingsConfigDict(env_prefix="GATEKEEPER_", env_file=".env", extra="ignore")

    hmac_key: str = Field(
        default="", description="Keyed-HMAC key for the audit hash-chain (ADR-003)."
    )
    env: str = Field(default="dev")
    log_level: str = Field(default="INFO")
    config_dir: Path = Field(default=Path("./config"))


# --- Security guard constants (fail-closed) --------------------------------
#: HMAC key values that must NEVER be allowed to boot (unset / placeholders).
_WEAK_HMAC_KEYS = frozenset(
    {"", "changeme", "change-me", "do-not-use", "example-hmac-key-do-not-use", "test", "secret"}
)
#: Minimum HMAC key length in chars (>= 32). Generate with `openssl rand -hex 32`.
_MIN_HMAC_LEN = 32


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file into a dict. Missing file -> empty (caller applies defaults)."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:  # fail-loud: a broken config file must not be ignored
        raise ConfigError(f"Could not parse {path}: {exc}") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def load_config(settings: Settings | None = None) -> dict[str, Any]:
    """Aggregate every config source into one dict.

    Returned shape::

        {"platform": {...}, "product": {...}, "upstreams": [...], "identities": [...]}

    Fail-loud: if the config dir is missing entirely, that is a misconfiguration, not a default.
    """
    settings = settings or get_settings()
    cfg_dir = settings.config_dir
    if not cfg_dir.exists():
        raise ConfigError(
            f"Config dir {cfg_dir!s} does not exist. "
            "Set GATEKEEPER_CONFIG_DIR or run from the repo root."
        )
    platform = _load_yaml(cfg_dir / "platform.yaml")
    product = _load_yaml(cfg_dir / "product.yaml")
    upstreams = _load_yaml(cfg_dir / "upstreams.yaml").get("upstreams", [])
    identities = _load_yaml(cfg_dir / "identities.yaml").get("principals", [])
    return {
        "platform": platform,
        "product": product,
        "upstreams": upstreams,
        "identities": identities,
    }


def validate_security(settings: Settings) -> None:
    """Fail-CLOSED security guard: refuse to boot without a real ledger HMAC key (ADR-003).

    Raises ``ConfigError`` if the key is unset, a known placeholder, or too short.
    """
    key = settings.hmac_key.strip()
    if key.lower() in _WEAK_HMAC_KEYS:
        raise ConfigError(
            "GATEKEEPER_HMAC_KEY is unset or a known-default placeholder. The audit "
            "ledger cannot be made tamper-evident without it. Generate one with "
            "`openssl rand -hex 32` and put it in .env. Refusing to boot (fail-closed)."
        )
    if len(key) < _MIN_HMAC_LEN:
        raise ConfigError(
            f"GATEKEEPER_HMAC_KEY is too short ({len(key)} chars); need >= {_MIN_HMAC_LEN}. "
            "Refusing to boot (fail-closed)."
        )


def boot() -> tuple[Settings, dict[str, Any]]:
    """Load settings + config and run the startup guard. Returns (settings, config) or raises.

    This is the single entrypoint every runnable command uses, so the security guard can never be
    bypassed by forgetting to call it.
    """
    settings = get_settings()
    config = load_config(settings)
    validate_security(settings)
    return settings, config
