"""Generic OIDC ``IdentityResolver`` (M3.2) — real IdP bearer tokens -> Principal, fail-closed.

Implements ``ports.identity.IdentityResolver`` (the port is UNCHANGED): a JWT issued by the
configured IdP is validated — JWKS signature, issuer, audience, expiry — and mapped to a
``Principal`` via a config-driven group->role map. Selected by ``platform.yaml``
``adapters.identity: oidc`` (a pure config swap; ``static_token`` stays the dev default).

Stack decision (mini-ADR-010, benchmarked 2026): **PyJWT + PyJWKClient** — the gateway is a
*resource server* (it validates tokens), so MSAL (a token-*acquisition* client library) is the
wrong tool; PyJWT's JWKS client with key caching is the standard, IdP-agnostic pattern (Entra ID,
Keycloak, Auth0, Okta all serve standard JWKS). Entra ID is the first PROVEN IdP (see the feature
doc's setup guide); nothing in this module is Entra-specific.

FAIL-CLOSED everywhere: any validation failure — bad signature, expired, wrong audience/issuer,
unmapped groups, JWKS unreachable — raises ``IdentityError`` (the pipeline then LEDGERS the deny
and refuses). No default principal, no default role, and the token value is never echoed into
errors or logs (it is a credential).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import jwt

from gatekeeper.config.loader import ConfigError
from gatekeeper.domain.errors import IdentityError
from gatekeeper.infra.logging import get_logger
from gatekeeper.schemas.models import Principal

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Signature algorithms accepted by default — asymmetric only. Symmetric (HS*) is NEVER allowed:
#: it would make the IdP's signing secret a shared secret with every verifier. "none" is rejected
#: by PyJWT by construction when an allowlist is passed.
_DEFAULT_ALGORITHMS = ("RS256",)
_DEFAULT_PRINCIPAL_CLAIM = "sub"
_DEFAULT_GROUPS_CLAIM = "groups"
#: How long fetched JWKS keys are cached (seconds). A refresh is one blocking HTTP fetch — rare
#: (key rollover), bounded by the timeout below, and recorded here as a deliberate trade.
_DEFAULT_JWKS_LIFESPAN_S = 900.0
_DEFAULT_HTTP_TIMEOUT_S = 10.0
#: OIDC discovery path appended to the issuer when no explicit jwks_url is configured.
_DISCOVERY_SUFFIX = "/.well-known/openid-configuration"


class OidcIdentityResolver:
    """Validate an IdP-issued JWT and map its groups claim to a gateway role (fail-closed)."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        group_role_map: Mapping[str, str],
        jwks_client: Any,  # anything with get_signing_key_from_jwt(token).key (seam for tests)
        algorithms: tuple[str, ...] = _DEFAULT_ALGORITHMS,
        principal_claim: str = _DEFAULT_PRINCIPAL_CLAIM,
        groups_claim: str = _DEFAULT_GROUPS_CLAIM,
        tenant: str = "default",
        leeway_s: float = 0.0,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._group_role_map = dict(group_role_map)
        self._jwks = jwks_client
        self._algorithms = list(algorithms)
        self._principal_claim = principal_claim
        self._groups_claim = groups_claim
        self._tenant = tenant
        self._leeway = leeway_s
        self._log = get_logger("gatekeeper.identity.oidc")

    # --- construction from config (no hardcoding; fail-loud on a broken section) -------------
    @classmethod
    def from_config(cls, oidc: Mapping[str, Any]) -> OidcIdentityResolver:
        """Build from the ``platform.yaml`` ``identity.oidc`` section.

        Required: ``issuer``, ``audience``, a non-empty ``group_role_map``. Optional:
        ``jwks_url`` (default: OIDC discovery on the issuer), ``algorithms``,
        ``principal_claim``, ``groups_claim``, ``tenant``, ``leeway_s``, ``jwks_lifespan_s``.
        """
        missing = [k for k in ("issuer", "audience") if not str(oidc.get(k, "")).strip()]
        group_role_map = dict(oidc.get("group_role_map") or {})
        if missing or not group_role_map:
            need = missing + ([] if group_role_map else ["group_role_map"])
            raise ConfigError(
                f"identity.oidc is missing {need} (platform.yaml). The OIDC adapter refuses "
                "to start half-configured (fail-loud) — every field is required so no caller "
                "can authenticate by accident."
            )
        issuer = str(oidc["issuer"]).rstrip("/")
        jwks_url = str(oidc.get("jwks_url", "")).strip() or _discover_jwks_url(issuer)
        jwks_client = jwt.PyJWKClient(
            jwks_url,
            cache_keys=True,
            lifespan=int(oidc.get("jwks_lifespan_s", _DEFAULT_JWKS_LIFESPAN_S)),
            timeout=int(oidc.get("http_timeout_s", _DEFAULT_HTTP_TIMEOUT_S)),
        )
        return cls(
            issuer=issuer,
            audience=str(oidc["audience"]),
            group_role_map={str(k): str(v) for k, v in group_role_map.items()},
            jwks_client=jwks_client,
            algorithms=tuple(str(a) for a in (oidc.get("algorithms") or _DEFAULT_ALGORITHMS)),
            principal_claim=str(oidc.get("principal_claim", _DEFAULT_PRINCIPAL_CLAIM)),
            groups_claim=str(oidc.get("groups_claim", _DEFAULT_GROUPS_CLAIM)),
            tenant=str(oidc.get("tenant", "default")),
            leeway_s=float(oidc.get("leeway_s", 0.0)),
        )

    # --- the port -----------------------------------------------------------------------------
    def resolve(self, token: str) -> Principal:
        """Validate ``token`` and return its Principal. Raises ``IdentityError`` on ANY failure.

        Only ``IdentityError`` ever escapes (the pipeline's fail-closed contract): an unexpected
        bug or a JWKS outage must surface as a DENY-and-ledger, never as an unhandled error that
        could skip the audit path.
        """
        if not token.strip():
            raise IdentityError("unknown or missing bearer token")
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key=signing_key.key,
                algorithms=self._algorithms,  # allowlist: rejects "none" and HS* downgrades
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            # The exception TYPE is safe to surface (expired/audience/signature...); the token
            # and claim values are not.
            raise IdentityError(f"oidc token rejected: {type(exc).__name__}") from exc
        except IdentityError:
            raise
        except Exception as exc:  # noqa: BLE001 — JWKS fetch/parse outage etc.: deny, never crash
            self._log.error(
                "oidc validation unavailable (failing closed)",
                extra={"error": type(exc).__name__},
            )
            raise IdentityError("oidc validation unavailable (failing closed)") from exc
        return self._principal_from_claims(claims)

    def _principal_from_claims(self, claims: Mapping[str, Any]) -> Principal:
        principal_id = str(claims.get(self._principal_claim, "")).strip()
        if not principal_id:
            raise IdentityError(f"oidc token rejected: missing {self._principal_claim!r} claim")
        raw_groups = claims.get(self._groups_claim)
        groups = [str(g) for g in raw_groups] if isinstance(raw_groups, list) else []
        # First match in MAP order wins — the operator's file ranks roles, deterministically.
        for group, role in self._group_role_map.items():
            if group in groups:
                return Principal(id=principal_id, role=role, tenant=self._tenant)
        # Authenticated but NOT authorized for any role: fail-closed, never a default role.
        raise IdentityError(
            f"oidc token rejected: no configured role for the caller's {self._groups_claim!r}"
        )


def _discover_jwks_url(issuer: str) -> str:
    """Resolve ``jwks_uri`` from the issuer's OIDC discovery document (standard, IdP-agnostic).

    Runs ONCE at adapter construction (boot), not per call. Fail-loud: a gateway configured for
    OIDC but unable to learn the IdP's keys must not start half-authenticated.
    """
    url = issuer + _DISCOVERY_SUFFIX
    try:
        response = httpx.get(url, timeout=_DEFAULT_HTTP_TIMEOUT_S)
        response.raise_for_status()
        jwks_uri = str(response.json().get("jwks_uri", "")).strip()
    except Exception as exc:
        raise ConfigError(
            f"OIDC discovery failed against {url}: {type(exc).__name__}. Set identity.oidc."
            "jwks_url explicitly or fix the issuer. Refusing to boot (fail-loud)."
        ) from exc
    if not jwks_uri:
        raise ConfigError(f"OIDC discovery document at {url} has no jwks_uri (fail-loud).")
    return jwks_uri
