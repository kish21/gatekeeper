"""Static token -> Principal resolver (M1 ``IdentityResolver`` stub).

Implements ``ports.identity.IdentityResolver``. The token map comes from ``config/identities.yaml``
(DEV/DEMO fakes); a real deployment swaps this adapter for OIDC via ``platform.yaml``
adapters.identity without touching the pipeline (ports & adapters), and upgrades bearer tokens to
sender-constrained tokens (ADR-006). FAIL-CLOSED: an unknown/empty token RAISES — never a default.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from gatekeeper.domain.errors import IdentityError
from gatekeeper.schemas.models import Principal


class StaticTokenResolver:
    """Resolve an opaque bearer token to a frozen ``Principal`` from a static map."""

    def __init__(self, token_map: Mapping[str, Principal]) -> None:
        self._by_token = dict(token_map)

    @classmethod
    def from_config(cls, identities: Sequence[Mapping[str, Any]]) -> StaticTokenResolver:
        """Build from the ``identities.yaml`` principals list (token/principal/role[/tenant])."""
        token_map: dict[str, Principal] = {}
        for raw in identities:
            token = str(raw["token"])
            token_map[token] = Principal(
                id=str(raw["principal"]),
                role=str(raw["role"]),
                tenant=str(raw.get("tenant", "default")),
            )
        return cls(token_map)

    def resolve(self, token: str) -> Principal:
        principal = self._by_token.get(token)
        if principal is None:
            # Do NOT echo the token value (it is a secret) — only that it was unrecognized.
            raise IdentityError("unknown or missing bearer token")
        return principal
