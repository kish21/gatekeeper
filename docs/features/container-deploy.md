# Feature — Container + Azure-first hosted deploy (M3.3)

> Build #8 · 2026-06-12 · the `#Plan` *"Infra / deploy"* trigger fired (2026-06 enterprise platform
> requirements). Cloud-neutral container; Azure Container Apps is the documented proof path.

## What it is

A production container for the gateway ([Dockerfile](../../Dockerfile)) plus the Azure deploy
guide ([docs/deploy/azure-container-apps.md](../deploy/azure-container-apps.md)):

- **Multi-stage image** (`python:3.12-slim`): wheel built in a build stage; runtime stage installs
  the wheel + the demo extra, runs as a **non-root** user (`uid 10001`).
- **Entrypoint = migrate, then serve:** `alembic upgrade head` (fail-loud — a failed migration
  stops the container) → `exec gatekeeper serve --transport http`.
- **Container config overlay** ([deploy/container/platform.yaml](../../deploy/container/platform.yaml)):
  HTTP on `0.0.0.0:8765` **with the explicit ADR-009 ack** (inside a container the bind is
  namespace-local; real exposure + TLS is the platform ingress's job), ledger at **`/data/audit.db`**
  (persistent volume), JSON logging. Mount your own dir over `/app/config` (or set
  `GATEKEEPER_CONFIG_DIR`) for a real deployment.
- **No secret in the image** (gitleaks-clean): `GATEKEEPER_HMAC_KEY` & co. arrive via the runtime
  environment; the committed identities are the dev demo placeholders, flagged smoke-only.
- **HEALTHCHECK** = the same `/healthz` the platform probes (stdlib urllib — no curl layer).
- **ADR-007 enforced operationally:** the guide pins `--min-replicas 1 --max-replicas 1`; a second
  replica would mean two ledger writers. Scale trigger ⇒ the deferred Postgres ledger.

## Exit criterion vs delivery (honest split)

| Clause | Status |
|---|---|
| Dockerfile + deploy guide | ✅ shipped (this doc + the guide) |
| Gateway runs in the container; ledger on persistent storage; secrets via env, none in image/config | ✅ proven **locally in the real container** (see verification) and gated **every push** by the CI `container` job (build → run → `/healthz` → in-container `gatekeeper verify`) |
| Runs **on Azure**; a local agent makes a governed call against the **cloud** gateway | ⏳ **user action** — needs the Azure subscription login. The guide is copy-paste end-to-end (`az acr build`, Container Apps env, Azure Files mount, secretref key, FQDN smoke). Code-wise nothing remains. |
| GCP guide | optional follow-up slice (no code change), as planned |

## How verified (live container, this session)

```
docker build -t gatekeeper:local .                       # multi-stage build OK
docker run -d -p 8765:8765 -v gk-ledger:/data \
  -e GATEKEEPER_HMAC_KEY=<random> gatekeeper:local       # migrate -> serve (single worker)
curl /healthz  -> {"status":"ok"}
MCP client over http://127.0.0.1:8765/mcp (Bearer dev token):
  list_tools -> demo-files tools; read_file welcome.txt -> ALLOW, transparent
  readonly token write_file -> denied (Cedar default-deny)
docker exec gatekeeper verify -> OK ledger intact (ledger on the /data volume)
curl /metrics -> live counters + overhead p95 vs budget (M3.4)
```

Plus in CI on every push: `container` job = build → boot with a generated key → `/healthz` within
30 s → `docker logs` surfaced → `gatekeeper verify` inside the container.

## Recorded limitations

- **Single replica = a brief restart window on updates** — the ADR-007 trade, stated in the guide.
- The image bundles the demo upstreams/identities for an out-of-the-box smoke; the guide's step 8
  ("make it real") swaps them for OIDC + the operator's own config before any real use, and adds
  the public FQDN to `transport.http_allowed_hosts` (the `/mcp` Host check 421s unknown hosts
  until then — deliberate fail-closed).
- ADR-006 (bearer replay) **comes into live view at hosted exposure**: guide mandates OIDC
  short-lived tokens for real use; DPoP/mTLS stays the recorded next step.
