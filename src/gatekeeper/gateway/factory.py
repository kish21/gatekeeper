"""Composition root — assemble the governed pipeline from config (no hardcoding, adapters by key).

Reads every knob back from config (``platform.yaml`` adapter selection + resilience,
``product.yaml`` write-detection, ``upstreams.yaml`` registry, ``identities.yaml`` map) so swapping
an implementation is a config edit, never code. Boots through the security guard (HMAC, ADR-003).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gatekeeper.adapters.identity.static_token import StaticTokenResolver
from gatekeeper.adapters.ledger.factory import open_ledger
from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.adapters.policy.cedar import CedarPolicyEngine
from gatekeeper.adapters.upstream.mcp_client import McpUpstreamClient
from gatekeeper.config.loader import ConfigError, boot
from gatekeeper.domain.classify import ActionClassifier
from gatekeeper.gateway.pipeline import GatewayPipeline
from gatekeeper.ports.identity import IdentityResolver
from gatekeeper.ports.policy import PolicyEngine

_DEFAULT_UPSTREAM_TIMEOUT = 30.0
_DEFAULT_POLICY_DIR = "./policies"


@dataclass
class GatewayRuntime:
    """The wired gateway + the resources it owns (closed together on shutdown)."""

    pipeline: GatewayPipeline
    identity: IdentityResolver
    upstream: McpUpstreamClient
    ledger: SqliteLedgerStore

    async def aclose(self) -> None:
        await self.upstream.aclose()
        self.ledger.close()


def _build_identity(platform: dict[str, Any], identities: list[dict[str, Any]]) -> IdentityResolver:
    kind = platform.get("adapters", {}).get("identity", "static_token")
    if kind != "static_token":
        raise ConfigError(
            f"identity adapter {kind!r} not supported yet (static_token only; OIDC deferred)."
        )
    return StaticTokenResolver.from_config(identities)


def _build_policy(platform: dict[str, Any]) -> PolicyEngine:
    kind = platform.get("adapters", {}).get("policy", "cedar")
    if kind != "cedar":
        raise ConfigError(f"policy adapter {kind!r} not supported yet (cedar only).")
    policy_dir = platform.get("policy", {}).get("dir", _DEFAULT_POLICY_DIR)
    return CedarPolicyEngine.from_config(policy_dir)  # fail-loud on a missing/unparseable policy


def _build_classifier(product: dict[str, Any], upstreams: list[dict[str, Any]]) -> ActionClassifier:
    write_detection = product.get("write_detection", {})
    annotations = {
        str(u["name"]): {"writes": list(u.get("writes", [])), "reads": list(u.get("reads", []))}
        for u in upstreams
    }
    return ActionClassifier(
        name_patterns=list(write_detection.get("name_patterns", [])),
        upstream_annotations=annotations,
    )


def build_runtime() -> GatewayRuntime:
    """Build the full gateway runtime from config. Fail-closed + fail-loud (``ConfigError``)."""
    settings, config = boot()
    platform, product = config["platform"], config["product"]
    upstreams = config["upstreams"]

    identity = _build_identity(platform, config["identities"])
    policy = _build_policy(platform)
    classifier = _build_classifier(product, upstreams)

    timeout = float(
        platform.get("resilience", {}).get("upstream", {}).get("timeout", _DEFAULT_UPSTREAM_TIMEOUT)
    )
    upstream = McpUpstreamClient.from_config(upstreams, timeout=timeout)
    # Reuse the settings/config already booted above (no second config load / guard run).
    ledger = open_ledger(settings, config)  # fail-loud "table must exist"

    pipeline = GatewayPipeline(
        identity=identity,
        classifier=classifier,
        policy=policy,
        ledger=ledger,
        upstream=upstream,
        hmac_key=settings.hmac_key,
    )
    return GatewayRuntime(pipeline=pipeline, identity=identity, upstream=upstream, ledger=ledger)
