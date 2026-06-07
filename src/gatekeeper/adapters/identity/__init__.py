"""Identity adapters (implement ports.IdentityResolver), selected via config adapters.identity.

    static_token.py  — token -> principal -> role from config/identities.yaml (M1 dev stub)
    oidc.py          — OIDC/SSO identity (deferred; trigger in PRODUCT.md Scope)
Sender-constrained-token verification (DPoP/mTLS, ADR-006) plugs in here when triggered.
"""
