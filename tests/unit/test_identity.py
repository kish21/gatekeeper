"""Unit tests for the static-token IdentityResolver (fail-closed contract)."""

from __future__ import annotations

import pytest

from gatekeeper.adapters.identity.static_token import StaticTokenResolver
from gatekeeper.domain.errors import IdentityError

IDENTITIES = [
    {"token": "tok-alice", "principal": "alice", "role": "operator"},
    {"token": "tok-bob", "principal": "bob", "role": "readonly", "tenant": "acme"},
]


def test_resolves_known_token_to_principal() -> None:
    resolver = StaticTokenResolver.from_config(IDENTITIES)
    principal = resolver.resolve("tok-alice")
    assert (principal.id, principal.role, principal.tenant) == ("alice", "operator", "default")


def test_tenant_is_honored_when_present() -> None:
    resolver = StaticTokenResolver.from_config(IDENTITIES)
    assert resolver.resolve("tok-bob").tenant == "acme"


@pytest.mark.parametrize("bad", ["", "unknown", "tok-ALICE", " tok-alice"])
def test_unknown_token_fails_closed(bad: str) -> None:
    resolver = StaticTokenResolver.from_config(IDENTITIES)
    with pytest.raises(IdentityError):
        resolver.resolve(bad)


def test_error_never_echoes_the_token() -> None:
    resolver = StaticTokenResolver.from_config(IDENTITIES)
    try:
        resolver.resolve("super-secret-token")
    except IdentityError as exc:
        assert "super-secret-token" not in str(exc)
