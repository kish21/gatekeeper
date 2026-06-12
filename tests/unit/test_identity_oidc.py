"""Unit — OIDC IdentityResolver (M3.2): REAL RS256 JWTs against the full fail-closed matrix.

Tokens are signed with a locally generated RSA key (a fake IdP); the JWKS client seam is stubbed
to return that key's public half, so signature/audience/expiry/groups validation is the REAL
PyJWT path with zero network. Every failure mode must raise IdentityError — never a default
principal, never a leaked token.
"""

from __future__ import annotations

import time
import types as pytypes
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from gatekeeper.adapters.identity.oidc import OidcIdentityResolver
from gatekeeper.adapters.identity.static_token import StaticTokenResolver
from gatekeeper.config.loader import ConfigError
from gatekeeper.domain.errors import IdentityError
from gatekeeper.gateway.factory import _build_identity

ISSUER = "https://idp.test/tenant"
AUDIENCE = "api://gatekeeper-test"
GROUP_OPS = "11111111-aaaa-4bbb-8ccc-000000000001"
GROUP_RO = "11111111-aaaa-4bbb-8ccc-000000000002"
ROLE_MAP = {GROUP_OPS: "operator", GROUP_RO: "readonly"}


def _keypair() -> tuple[str, Any]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


PRIVATE_PEM, PUBLIC_KEY = _keypair()
OTHER_PRIVATE_PEM, _ = _keypair()


class StubJwks:
    """Stands in for PyJWKClient: always serves OUR fake IdP's public key."""

    def __init__(self, public_key: Any = PUBLIC_KEY) -> None:
        self._key = public_key

    def get_signing_key_from_jwt(self, token: str) -> Any:
        return pytypes.SimpleNamespace(key=self._key)


class BrokenJwks:
    """A JWKS endpoint outage (network error on key fetch)."""

    def get_signing_key_from_jwt(self, token: str) -> Any:
        raise ConnectionError("jwks endpoint unreachable")


def _claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": "alice@example.test",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": now + 600,
        "iat": now,
        "groups": [GROUP_OPS],
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def _token(key: str = PRIVATE_PEM, alg: str = "RS256", **overrides: Any) -> str:
    return jwt.encode(_claims(**overrides), key, algorithm=alg)


def _resolver(jwks: Any | None = None, **kw: Any) -> OidcIdentityResolver:
    return OidcIdentityResolver(
        issuer=ISSUER,
        audience=AUDIENCE,
        group_role_map=ROLE_MAP,
        jwks_client=jwks or StubJwks(),
        **kw,
    )


def test_valid_token_resolves_principal_and_role() -> None:
    principal = _resolver().resolve(_token())
    assert principal.id == "alice@example.test"
    assert principal.role == "operator"
    assert principal.tenant == "default"


def test_map_order_ranks_roles_first_match_wins() -> None:
    # A caller in BOTH groups gets the FIRST mapped role — the config file ranks precedence.
    principal = _resolver().resolve(_token(groups=[GROUP_RO, GROUP_OPS]))
    assert principal.role == "operator"


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ({"exp": int(time.time()) - 60}, "ExpiredSignature"),
        ({"aud": "api://someone-else"}, "InvalidAudience"),
        ({"iss": "https://evil.test"}, "InvalidIssuer"),
        ({"exp": None}, "MissingRequiredClaim"),  # exp is REQUIRED, not optional
        ({"groups": ["unmapped-group-id"]}, "no configured role"),
        ({"groups": None}, "no configured role"),  # claim absent entirely
        ({"groups": "not-a-list"}, "no configured role"),  # malformed claim shape
        ({"sub": None}, "missing 'sub' claim"),
    ],
)
def test_invalid_claims_fail_closed(mutation: dict[str, Any], match: str) -> None:
    with pytest.raises(IdentityError, match=match):
        _resolver().resolve(_token(**mutation))


def test_forged_signature_fails_closed() -> None:
    # Signed by a DIFFERENT private key than the IdP's published JWKS -> signature mismatch.
    with pytest.raises(IdentityError, match="InvalidSignature|VerificationError"):
        _resolver().resolve(_token(key=OTHER_PRIVATE_PEM))


def test_symmetric_alg_downgrade_is_rejected() -> None:
    # HS256 signed with a guessable secret must never pass the asymmetric-only allowlist.
    forged = jwt.encode(_claims(), "guessable-secret", algorithm="HS256")
    with pytest.raises(IdentityError):
        _resolver().resolve(forged)


def test_empty_token_fails_closed() -> None:
    with pytest.raises(IdentityError, match="unknown or missing bearer token"):
        _resolver().resolve("   ")


def test_jwks_outage_fails_closed_not_open() -> None:
    with pytest.raises(IdentityError, match="failing closed"):
        _resolver(jwks=BrokenJwks()).resolve(_token())


def test_error_never_echoes_the_token() -> None:
    token = _token(aud="api://someone-else")
    with pytest.raises(IdentityError) as err:
        _resolver().resolve(token)
    assert token not in str(err.value)  # a credential never lands in an error message


def test_custom_claims_and_tenant_flow_from_config() -> None:
    resolver = _resolver(principal_claim="oid", groups_claim="roles", tenant="acme")
    token = _token(oid="object-123", roles=[GROUP_OPS])
    principal = resolver.resolve(token)
    assert (principal.id, principal.role, principal.tenant) == ("object-123", "operator", "acme")


# --- from_config / factory dispatch (fail-loud wiring) ----------------------------------------
def test_from_config_refuses_half_configuration() -> None:
    with pytest.raises(ConfigError, match="identity.oidc is missing"):
        OidcIdentityResolver.from_config({"issuer": ISSUER})  # no audience, no map


def test_factory_dispatches_identity_adapter_by_config_key() -> None:
    oidc_platform = {
        "adapters": {"identity": "oidc"},
        "identity": {
            "oidc": {
                "issuer": ISSUER,
                "audience": AUDIENCE,
                "group_role_map": ROLE_MAP,
                "jwks_url": "https://idp.test/jwks",  # explicit -> no discovery fetch at build
            }
        },
    }
    assert isinstance(_build_identity(oidc_platform, []), OidcIdentityResolver)
    assert isinstance(
        _build_identity({"adapters": {"identity": "static_token"}}, []), StaticTokenResolver
    )
    with pytest.raises(ConfigError, match="not supported"):
        _build_identity({"adapters": {"identity": "ldap"}}, [])
