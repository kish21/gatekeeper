# Feature — OIDC identity adapter (M3.2)

> Build #7 · 2026-06-12 · pulls the deferred *"SSO / OIDC identity integration"* row in on its fired
> trigger (2026-06 enterprise platform requirements). Generic across IdPs; **Entra ID is the
> documented-first IdP** (setup guide below).

## What it is

`OidcIdentityResolver` — a second implementation of the **unchanged** `IdentityResolver` port:
a real IdP-issued JWT arriving as the per-request `Authorization: Bearer` (M3.1, ADR-008) is
validated — **JWKS signature, issuer, audience, expiry** — and mapped to a `Principal` through a
config-driven **group→role map**. Selected purely by config:

```yaml
# config/platform.yaml
adapters:
  identity: oidc        # static_token stays the dev default
identity:
  oidc:
    issuer: https://login.microsoftonline.com/<tenant-id>/v2.0
    audience: <client-id or api://… identifier URI>
    group_role_map:
      <group-object-id>: operator   # map order ranks roles; first match wins
      <group-object-id>: readonly   # unmapped groups -> DENY
```

**Stack (mini-ADR-010, benchmarked 2026):** PyJWT + `PyJWKClient` (cached keys), not MSAL — the
gateway is a resource server that *validates* tokens; MSAL is a token-*acquisition* library.
PyJWT+JWKS is the standard IdP-agnostic pattern (Entra/Keycloak/Auth0/Okta all serve JWKS).
Rejected: python-jose (maintenance/CVE history), authlib (heavier, no added value here).

## Fail-closed matrix (every row asserted by a unit test, real RS256 tokens)

| Attack / failure | Outcome |
|---|---|
| Expired token · wrong audience · wrong issuer · missing `exp` | `IdentityError` (pipeline ledgers the deny) |
| Forged signature (key not in the IdP's JWKS) | `IdentityError` |
| Algorithm downgrade (HS256 with a guessable secret, `none`) | rejected — asymmetric-only allowlist; HS*/none are never accepted |
| Groups unmapped / missing / malformed | `IdentityError` — authenticated ≠ authorized; **no default role, ever** |
| JWKS endpoint outage | `IdentityError` "failing closed" — an IdP outage denies, it never bypasses |
| Any unexpected exception | mapped to `IdentityError` — only that type escapes, so the audit path can never be skipped by a crash |
| Error messages | carry the exception TYPE only; the token (a credential) is never echoed into errors, logs, or the ledger (asserted) |

Boot is fail-loud: a half-configured `identity.oidc` (missing issuer/audience/map) or failed OIDC
discovery refuses to start. Keys are cached (`jwks_lifespan_s`, default 900 s); the rare refresh is
one bounded blocking fetch — recorded trade, same shape as the ledger-fsync trade in ADR-007.

## How verified

- **Unit (16):** [tests/unit/test_identity_oidc.py](../../tests/unit/test_identity_oidc.py) — locally
  generated RSA keypair = a fake IdP; only the JWKS *fetch* is stubbed, so signature/aud/exp/groups
  run the real PyJWT path. Full matrix above + claim/tenant configurability + factory dispatch
  (`static_token` | `oidc` | unknown→`ConfigError`).
- **Integration (2, live HTTP):** [tests/integration/test_oidc_http.py](../../tests/integration/test_oidc_http.py)
  — real uvicorn + real MCP client + real subprocess upstream, JWTs in `Authorization: Bearer`:
  operator-group JWT allowed (ledger principal = the JWT subject) · readonly-group JWT
  Cedar-denied · expired JWT ledgered as `<unauthenticated>` DENY · group-membership change flips
  the role with **zero gateway change** · chain `verify`-clean · no JWT in the ledger.

**Honest gap (user action required):** the *"real Entra-issued token"* clause of the exit criterion
needs a real tenant. Everything except the JWKS fetch is proven against real tokens; the Entra proof
is a config-only exercise:

1. **Entra ID → App registrations → New**: name `gatekeeper`; note the **Application (client) ID**
   (= `audience`) and **Directory (tenant) ID** (`issuer = https://login.microsoftonline.com/<tenant-id>/v2.0`).
2. **Token configuration → Add groups claim** (Security groups → as group IDs).
3. Create two security groups (ops / readonly), note their **object IDs** → `group_role_map`.
4. Set `adapters.identity: oidc` + the section above; run `gatekeeper serve --transport http`.
5. Acquire a token for that audience (e.g. `az account get-access-token --resource <client-id>`,
   or any MCP host's OAuth flow) and call through the gateway; `gatekeeper tail` shows the UPN/sub
   as principal.

## Code

- [src/gatekeeper/adapters/identity/oidc.py](../../src/gatekeeper/adapters/identity/oidc.py) — the adapter (validation, mapping, discovery).
- [src/gatekeeper/gateway/factory.py](../../src/gatekeeper/gateway/factory.py) — `_build_identity` config dispatch.
- [config/platform.yaml](../../config/platform.yaml) — `identity.oidc` documented section (commented; `static_token` remains default).

## Recorded limitations

- **Bearer JWTs are still replayable within their lifetime** (ADR-006). OIDC arriving = the ADR-006
  re-evaluation point: the mitigation path (DPoP/mTLS-bound tokens) stays deferred until the gateway
  is actually exposed beyond loopback (M3.3 ingress decides); short token lifetimes + TLS at the
  ingress are the interim posture.
- Group→role uses ONE claim (`groups_claim`); nested/transitive group resolution (Entra "groups
  overage" for >200 groups) is out — the runbook says use direct security groups for gateway roles.
