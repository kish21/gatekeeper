"""Identity port: opaque token -> Principal. Implemented by adapters.identity.*."""

from __future__ import annotations

from typing import Protocol

from gatekeeper.schemas.models import Principal


class IdentityResolver(Protocol):
    """Resolve a caller token to a Principal.

    Contract: an unknown/invalid/expired token MUST raise (fail-closed) — never return an anonymous
    or default principal.
    """

    def resolve(self, token: str) -> Principal: ...
