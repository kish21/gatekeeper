# Feature — Container + Azure-first hosted deploy (M3.3)

> Build #8 · 2026-06-12 · the `#Plan` *"Infra / deploy"* trigger fired (2026-06 enterprise platform
> requirements). Cloud-neutral container; Azure Container Apps is the documented proof path.

## What it is

A production container for the gateway ([Dockerfile](../../Dockerfile)) plus the Azure deploy
guide ([docs/deploy/azure-container-apps.md](../deploy/azure-container-apps.md)):

- **Multi-stage image** (`python:3.12-slim`): wheel built in a build stage; runtime stage installs
  the wheel + the demo extra, runs as a **non-root** user (`uid 10001`).
- **Entrypoint = serve.** The gateway creates or migrates its ledger on boot (fail-loud — a
  failed migration stops the container).
- **Container configuration is plain environment** (`ENV` in the Dockerfile, overridable at run
  time): HTTP on `0.0.0.0:8765` with the explicit non-loopback acknowledgement (inside a container
  the bind is namespace-local; real exposure + TLS is the platform ingress's job), ledger at
  **`/data/audit.db`**. There is no baked config overlay any more, so nothing can drift from
  `config/platform.yaml`. Mount your own dir over `/app/config` (or set `GATEKEEPER_CONFIG_DIR`)
  to change servers or policy.
- **Public hostname trusted automatically:** Azure's `CONTAINER_APP_HOSTNAME` is allow-listed at
  boot; other platforms set `GATEKEEPER_HTTP_ALLOWED_HOSTS`.
- **Demo tokens refused on a public bind** unless `GATEKEEPER_ALLOW_DEMO_TOKENS=1` (smoke tests);
  a deployment carries its own tokens in `GATEKEEPER_IDENTITIES` or uses OIDC.
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
- The image bundles the demo upstreams for an out-of-the-box smoke. The demo identities are only
  usable on a public bind with an explicit opt-in; the Azure script issues fresh tokens instead.
- **The hosted ledger is not durable across a replica restart yet** (Azure Files SMB corrupts
  SQLite; a durable store is the tracked follow-up — see the deploy guide).
- ADR-006 (bearer replay) **comes into live view at hosted exposure**: guide mandates OIDC
  short-lived tokens for real use; DPoP/mTLS stays the recorded next step.
