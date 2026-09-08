"""Typed configuration loader + startup guard — the no-hardcoding engine.

Sources, highest precedence first:
  1. Process environment            -> ``GATEKEEPER_*`` secrets + overrides (``Settings``)
  2. ``.env``                       -> same names, read from the project root
  3. ``config/platform.yaml``       -> engine/technical knobs
  4. ``config/product.yaml``        -> product/business knobs
Plus deployment data: ``config/upstreams.yaml`` (registry) and ``config/identities.yaml`` (dev map).

**Every knob a hosted deployment needs at runtime can be set from the environment** (see
``Settings``), so a container never has to bake a hostname or a ledger path into its image.

**Paths resolve against the project root**, not the current working directory: the root is the
parent of the config dir. That is what makes ``gatekeeper serve`` work when an MCP host (Claude
Desktop, an IDE) launches it from an arbitrary directory — set ``GATEKEEPER_CONFIG_DIR`` to an
absolute path and everything else (``.env``, the ledger, the policies) follows.

Secrets NEVER live in YAML — only their *names* appear there; values come from the environment.
The startup guard (``validate_security`` / ``boot``) is **fail-loud on misconfig** and
**fail-closed on security**: the gateway refuses to boot without a real HMAC key, because that key
is what makes the audit ledger tamper-evident. A silent insecure boot is not an option.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised when configuration is missing, unparseable, or insecure. Boot must abort."""


#: The .env file every secret is read from. Looked up in the project root (config dir's parent),
#: falling back to the current directory so a plain ``cd repo && gatekeeper ...`` keeps working.
ENV_FILE = ".env"

#: Azure Container Apps injects the app's public hostname here. Trusting it automatically means a
#: hosted deploy never has to learn its own FQDN and rebuild the image to allow-list it.
_PLATFORM_HOSTNAME_VARS = ("CONTAINER_APP_HOSTNAME",)


class Settings(BaseSettings):
    """Secrets and environment-level overrides (``GATEKEEPER_*`` in the env or ``.env``).

    Every field here can be left empty: an empty value means "use the YAML / built-in default".
    """

    model_config = SettingsConfigDict(env_prefix="GATEKEEPER_", env_file=ENV_FILE, extra="ignore")

    # --- secrets -------------------------------------------------------------------------------
    hmac_key: str = Field(default="", description="Keyed-HMAC key for the audit hash-chain.")
    agent_token: str = Field(
        default="",
        description="Bearer token the agent presents to the stdio gateway (-> a Principal).",
    )
    alert_webhook: str = Field(
        default="",
        description="Operator alert webhook URL (Slack/Teams/PagerDuty-style). Empty = off.",
    )

    # --- where things live ---------------------------------------------------------------------
    env: str = Field(default="dev")
    log_level: str = Field(default="INFO")
    config_dir: Path = Field(default=Path("./config"))
    ledger_path: str = Field(default="", description="Overrides platform.yaml ledger.path.")
    policy_dir: str = Field(default="", description="Overrides platform.yaml policy.dir.")

    # --- transport (overrides platform.yaml transport.*) ---------------------------------------
    transport: str = Field(default="", description="stdio | http")
    http_host: str = Field(default="")
    http_port: int | None = Field(default=None)
    http_path: str = Field(default="")
    http_allow_non_loopback: bool | None = Field(default=None)
    http_allowed_hosts: str = Field(
        default="", description="Comma-separated extra Host values (a hosted FQDN)."
    )
    http_allowed_origins: str = Field(default="", description="Comma-separated Origin allowlist.")

    # --- identity (overrides platform.yaml adapters.identity + identity.oidc.*) ----------------
    identity: str = Field(default="", description="static_token | oidc")
    oidc_issuer: str = Field(default="")
    oidc_audience: str = Field(default="")
    oidc_group_role_map: str = Field(
        default="", description="Comma-separated 'group-id=role' pairs, first match wins."
    )
    oidc_jwks_url: str = Field(default="")
    oidc_principal_claim: str = Field(default="")
    oidc_groups_claim: str = Field(default="")

    identities: str = Field(
        default="",
        description="Replaces config/identities.yaml: 'principal:role:token;principal:role:token'. "
        "Lets a hosted deployment carry its own tokens as a platform secret.",
    )

    # --- approval (overrides product.yaml approval.*) ------------------------------------------
    approval_writes: str = Field(default="", description="require | off")
    approval_timeout_s: float | None = Field(default=None)

    # --- the web UI ---------------------------------------------------------------------------
    ui_token: str = Field(
        default="",
        description="Required to open the UI when the gateway is reachable beyond this machine.",
    )
    ui_port: int = Field(default=8770, description="Port for `gatekeeper ui`.")

    # --- guards ---------------------------------------------------------------------------------
    allow_demo_tokens: bool = Field(
        default=False,
        description="Permit the committed placeholder tokens on a network-reachable bind "
        "(smoke tests only — never for real use).",
    )

    @property
    def project_root(self) -> Path:
        """The directory every relative path resolves against: the config dir's parent."""
        return self.config_dir.resolve().parent


# --- Security guard constants (fail-closed) --------------------------------
#: HMAC key values that must NEVER be allowed to boot (unset / placeholders).
_WEAK_HMAC_KEYS = frozenset(
    {"", "changeme", "change-me", "do-not-use", "example-hmac-key-do-not-use", "test", "secret"}
)
#: Minimum HMAC key length in chars (>= 32). Generate with `gatekeeper init`.
_MIN_HMAC_LEN = 32

#: Default ledger DB path when not set anywhere.
DEFAULT_LEDGER_PATH = "./.gatekeeper/audit.db"
#: Default policy dir when not set anywhere.
DEFAULT_POLICY_DIR = "./policies"

#: Suffix of the committed demo tokens in ``config/identities.yaml``. They are public knowledge.
PLACEHOLDER_TOKEN_SUFFIX = "-REPLACE-ME"  # noqa: S105 — a marker, not a credential


def ledger_path(config: dict[str, Any]) -> str:
    """The configured ledger DB path (platform.yaml -> ledger.path), or the default. One source."""
    return str(config["platform"].get("ledger", {}).get("path", DEFAULT_LEDGER_PATH))


def policy_dir(config: dict[str, Any]) -> str:
    """The configured policy dir (platform.yaml -> policy.dir), or the default. One source."""
    return str(config["platform"].get("policy", {}).get("dir", DEFAULT_POLICY_DIR))


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file into a dict. Missing file -> empty (caller applies defaults)."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:  # fail-loud: a broken config file must not be ignored
        raise ConfigError(f"Could not parse {path}: {exc}") from exc


def env_file_path(settings: Settings | None = None) -> Path:
    """Where ``.env`` is read from: the project root if it has one, else the current directory."""
    if settings is None:
        settings = Settings()
    root_env = settings.project_root / ENV_FILE
    return root_env if root_env.is_file() else Path(ENV_FILE)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings from the process env + the project-root ``.env`` (root wins over cwd lookup)."""
    settings = Settings()
    env_path = env_file_path(settings)
    if env_path != Path(ENV_FILE):
        settings = Settings(_env_file=env_path)  # type: ignore[call-arg]
    return settings


def secret_source() -> dict[str, str]:
    """Lookup table for upstream credential references (``{from_env: NAME}`` in upstreams.yaml).

    Values come from ``.env`` (so a secret stays out of ``config/upstreams.yaml`` — only its NAME is
    in YAML), overlaid by real process environment variables — an exported var wins over ``.env``,
    the conventional precedence, so prod can inject secrets via the deployment environment. A
    missing ``.env`` simply yields the process environment. Resolved values are never logged.
    """
    file_values = {
        k: v for k, v in dotenv_values(env_file_path(get_settings())).items() if v is not None
    }
    return {**file_values, **os.environ}


def _apply_env_overrides(config: dict[str, Any], settings: Settings) -> None:
    """Fold ``GATEKEEPER_*`` runtime overrides into the loaded YAML (env wins, in place)."""
    platform = config["platform"]
    transport = platform.setdefault("transport", {})
    if settings.transport:
        transport["mode"] = settings.transport
    if settings.http_host:
        transport["http_host"] = settings.http_host
    if settings.http_port is not None:
        transport["http_port"] = settings.http_port
    if settings.http_path:
        transport["http_path"] = settings.http_path
    if settings.http_allow_non_loopback is not None:
        transport["http_allow_non_loopback"] = settings.http_allow_non_loopback
    extra_hosts = _split_csv(settings.http_allowed_hosts)
    extra_hosts += [os.environ[v] for v in _PLATFORM_HOSTNAME_VARS if os.environ.get(v)]
    if extra_hosts:
        transport["http_allowed_hosts"] = [
            *(transport.get("http_allowed_hosts") or []),
            *extra_hosts,
        ]
    if settings.http_allowed_origins:
        transport["http_allowed_origins"] = [
            *(transport.get("http_allowed_origins") or []),
            *_split_csv(settings.http_allowed_origins),
        ]

    product = config["product"]
    if settings.approval_writes:
        product.setdefault("approval", {})["writes"] = settings.approval_writes
    if settings.approval_timeout_s is not None:
        product.setdefault("approval", {})["timeout_s"] = settings.approval_timeout_s

    if settings.ledger_path:
        platform.setdefault("ledger", {})["path"] = settings.ledger_path
    if settings.policy_dir:
        platform.setdefault("policy", {})["dir"] = settings.policy_dir

    if settings.identity:
        platform.setdefault("adapters", {})["identity"] = settings.identity
    oidc_overrides: dict[str, Any] = {
        "issuer": settings.oidc_issuer,
        "audience": settings.oidc_audience,
        "jwks_url": settings.oidc_jwks_url,
        "principal_claim": settings.oidc_principal_claim,
        "groups_claim": settings.oidc_groups_claim,
    }
    oidc_overrides = {k: v for k, v in oidc_overrides.items() if v}
    group_map: dict[str, str] = {}
    for pair in _split_csv(settings.oidc_group_role_map):
        group, sep, role = pair.partition("=")
        if not sep or not group.strip() or not role.strip():
            raise ConfigError(
                "GATEKEEPER_OIDC_GROUP_ROLE_MAP must be 'group-id=role,group-id=role' "
                f"(got {pair!r})."
            )
        group_map[group.strip()] = role.strip()
    if group_map:
        oidc_overrides["group_role_map"] = group_map
    if oidc_overrides:
        oidc = (platform.setdefault("identity", {}) or {}).setdefault("oidc", {}) or {}
        oidc.update(oidc_overrides)
        platform["identity"]["oidc"] = oidc


def _parse_identities(spec: str) -> list[dict[str, Any]]:
    """``principal:role:token;...`` -> the same shape as ``identities.yaml`` ``principals``."""
    principals: list[dict[str, Any]] = []
    for item in (part.strip() for part in spec.split(";") if part.strip()):
        fields = item.split(":", 2)
        if len(fields) != 3 or not all(f.strip() for f in fields):
            raise ConfigError(
                "GATEKEEPER_IDENTITIES must be 'principal:role:token' entries separated by ';' "
                f"(got {item!r})."
            )
        principal, role, token = (f.strip() for f in fields)
        principals.append({"principal": principal, "role": role, "token": token})
    return principals


def _resolve_paths(config: dict[str, Any], root: Path) -> None:
    """Make the ledger + policy paths absolute against the project root (in place)."""
    platform = config["platform"]
    ledger = platform.setdefault("ledger", {})
    ledger["path"] = str(_absolute(ledger.get("path", DEFAULT_LEDGER_PATH), root))
    policy = platform.setdefault("policy", {})
    policy["dir"] = str(_absolute(policy.get("dir", DEFAULT_POLICY_DIR), root))


def _absolute(path: str | Path, root: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else (root / candidate)


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
            "Set GATEKEEPER_CONFIG_DIR to the absolute path of the project's config/ folder "
            "(or run from the project root)."
        )
    config = {
        "platform": _load_yaml(cfg_dir / "platform.yaml"),
        "product": _load_yaml(cfg_dir / "product.yaml"),
        "upstreams": _load_yaml(cfg_dir / "upstreams.yaml").get("upstreams", []),
        "identities": _load_yaml(cfg_dir / "identities.yaml").get("principals", []),
    }
    _apply_env_overrides(config, settings)
    if settings.identities:
        config["identities"] = _parse_identities(settings.identities)
    _resolve_paths(config, settings.project_root)
    return config


def validate_security(settings: Settings) -> None:
    """Fail-CLOSED security guard: refuse to boot without a real ledger HMAC key.

    Raises ``ConfigError`` if the key is unset, a known placeholder, or too short.
    """
    key = settings.hmac_key.strip()
    if key.lower() in _WEAK_HMAC_KEYS:
        raise ConfigError(
            "GATEKEEPER_HMAC_KEY is unset or a known-default placeholder. The audit "
            "ledger cannot be made tamper-evident without it. Run `gatekeeper init` to generate "
            "one into .env. Refusing to boot (fail-closed)."
        )
    if len(key) < _MIN_HMAC_LEN:
        raise ConfigError(
            f"GATEKEEPER_HMAC_KEY is too short ({len(key)} chars); need >= {_MIN_HMAC_LEN}. "
            "Refusing to boot (fail-closed)."
        )


def has_placeholder_tokens(identities: list[dict[str, Any]]) -> bool:
    """True when the identity map still carries the committed, publicly known demo tokens."""
    return any(str(i.get("token", "")).endswith(PLACEHOLDER_TOKEN_SUFFIX) for i in identities)


def boot() -> tuple[Settings, dict[str, Any]]:
    """Load settings + config and run the startup guard. Returns (settings, config) or raises.

    This is the single entrypoint every runnable command uses, so the security guard can never be
    bypassed by forgetting to call it.
    """
    settings = get_settings()
    config = load_config(settings)
    validate_security(settings)
    return settings, config
