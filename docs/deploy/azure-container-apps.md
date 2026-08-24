# Deploy — Azure Container Apps (M3.3, Azure-first proof)

> The container is **cloud-neutral** ([Dockerfile](../../Dockerfile)); this guide is the Azure-first
> proof path. A GCP (Cloud Run) guide is an optional follow-up slice — same image, no code change.

## Fastest path: the one-shot script

After `az login`, the whole sequence below is also an **idempotent script** — run it from the repo root:

```bash
bash scripts/deploy_azure.sh        # ACR build -> env -> Azure Files ledger -> 1-replica deploy -> /healthz
```

It preflight-checks your login, creates billable resources on your **current** subscription (override
names via `GK_RG`, `GK_LOCATION`, … env vars), sets the HMAC key **once** (re-runs keep it so the
ledger stays verifiable), mounts the ledger volume, and waits for `/healthz`. It then prints the live
URL and the "make it real" follow-ups (allow-list the FQDN + switch to OIDC, step 8 below). The manual
steps below explain what it does, step by step.

## ⚠ BLOCKER — the ledger does NOT persist on Azure Files (SMB)

> **Measured on the first live run, 2026-08-24.** This guide's storage choice is **known-broken** and
> is kept here only until the replacement lands. Deploy for a governance demo; **do not trust the
> audit trail** on this path.

What was observed on a real deployment, after governed calls had been served successfully:

| Evidence | Result |
|---|---|
| `ls -la /data` after governed traffic | `audit.db` **0 bytes**, with a stale `audit.db-journal` |
| `gatekeeper tail` (2nd process, same volume) | `Ledger table not found` — the DB is incoherent between processes |
| `ls -la /data` after a revision restart | `audit.db` **still 0 bytes**, journal gone — **records lost** |

**Cause:** SQLite depends on POSIX advisory locking and honest `fsync`. Azure Files **SMB** provides
neither reliably over the network, so commits are not durable and a second process cannot read a
consistent database. (Microsoft's own guidance advises against SQLite on Azure Files SMB.) This is a
*storage* defect, not a gateway defect — the governance path itself measured clean (see the runbook's
checks 1-7).

**Consequence for the exit criterion:** M3.3's *"ledger on persistent storage; `verify` clean"* clause
is **failed, not pending**. Governance over HTTPS is proven; durable audit on this storage is not.

**Candidate fixes (a design decision, not a patch — pick one deliberately):**
1. **Azure Files NFS v4.1** (Premium FileStorage) — keeps SQLite + the single-writer ADR-007 model;
   NFS supports the locking SQLite needs. Smallest change; costs more than Standard SMB.
2. **A managed disk / block volume** — real block storage, the semantics SQLite assumes.
3. **Promote the hosted ledger to Postgres** behind the existing `LedgerStore` port — no longer
   single-writer-by-construction, so the hash-chain's serialization has to move into the DB. Biggest
   change, and the one that also unblocks multi-replica scale.

Tracked as a follow-up; the gateway's SQLite ledger remains correct on local disk (181 tests green).

## Posture (what the ADRs require of ANY deployment)

| Rule | Why | Enforced by |
|---|---|---|
| **Exactly 1 replica** (`min-replicas 1 --max-replicas 1`) | ADR-007: the SQLite ledger has ONE writer by construction; a second replica = two hash-chain writers = a correctness bug dressed as scalability. Scale trigger ⇒ the deferred Postgres ledger, not more replicas. | you, below — and the runbook check |
| **TLS at the ingress, never in-process** | ADR-009 | Container Apps ingress (automatic HTTPS) |
| **Secrets via environment only** | no secret in image/config (repo rule) | Container Apps secrets → env refs |
| **Ledger on a persistent volume** | the audit chain must outlive any replica | Azure Files mount at `/data` — **but see the BLOCKER below: SMB does not deliver this** |
| **Real identity for real exposure** | a hosted gateway is beyond loopback ⇒ the ADR-006 bearer-replay threat is LIVE. The image's default `static_token` demo tokens are for a smoke test only — switch to **OIDC** ([feature doc](../features/oidc-identity.md)) before pointing anything real at it. | you — step 7 |

```mermaid
flowchart LR
    AG(["Local agent /<br/>MCP host"]) -->|"HTTPS · Bearer (OIDC)"| ING
    subgraph azure["Azure Container Apps"]
        direction TB
        ING["Ingress — TLS terminates here<br/>(ADR-009)"] --> APP["gatekeeper container<br/>1 replica = single ledger writer (ADR-007)<br/>:8765 → /mcp + /healthz"]
        APP --> VOL[("Azure Files /data<br/>tamper-evident ledger — persists across restarts")]
    end
    SEC["Secrets via env only<br/>HMAC key · no secret in image"]:::note -.-> APP
    IDP(["Entra ID / OIDC"]):::note -.->|"validate token (JWKS)"| APP
    classDef note fill:#fff8e1,stroke:#cc9900
```

## Steps (resource names are examples; pick your own)

```bash
RG=gatekeeper-rg; LOC=westeurope; ACR=gatekeeperacr$RANDOM; APP=gatekeeper
ENV=gatekeeper-env; SA=gatekeeperled$RANDOM; SHARE=ledger

# 1. Resource group + registry; build the image IN Azure (no local docker needed)
az group create -n $RG -l $LOC
az acr create -n $ACR -g $RG --sku Basic --admin-enabled true
az acr build -r $ACR -t gatekeeper:latest .

# 2. Container Apps environment
az extension add -n containerapp --upgrade
az containerapp env create -n $ENV -g $RG -l $LOC

# 3. Persistent ledger storage (Azure Files -> /data)
az storage account create -n $SA -g $RG -l $LOC --sku Standard_LRS
az storage share-rm create -g $RG --storage-account $SA -n $SHARE   # -g required: name, not id
KEY=$(az storage account keys list -n $SA -g $RG --query '[0].value' -o tsv)
az containerapp env storage set -n $ENV -g $RG --storage-name ledger \
  --azure-file-account-name $SA --azure-file-account-key "$KEY" \
  --azure-file-share-name $SHARE --access-mode ReadWrite

# 4. The app: 1 replica (ADR-007), secret-backed HMAC key, external HTTPS ingress
az containerapp create -n $APP -g $RG --environment $ENV \
  --registry-server $ACR.azurecr.io \
  --image $ACR.azurecr.io/gatekeeper:latest \
  --target-port 8765 --ingress external \
  --min-replicas 1 --max-replicas 1 \
  --secrets hmac-key="$(openssl rand -hex 32)" \
  --env-vars GATEKEEPER_HMAC_KEY=secretref:hmac-key

# 5. Mount the ledger volume at /data (YAML patch — volumes need the update flow)
az containerapp show -n $APP -g $RG -o yaml > app.yaml
#   in app.yaml under template:  add
#     volumes: [{name: ledger, storageName: ledger, storageType: AzureFile}]
#   and under the container:     add
#     volumeMounts: [{volumeName: ledger, mountPath: /data}]
az containerapp update -n $APP -g $RG --yaml app.yaml && rm app.yaml

# 6. Probes (liveness/readiness = /healthz; same YAML flow if you want them explicit)
FQDN=$(az containerapp show -n $APP -g $RG --query properties.configuration.ingress.fqdn -o tsv)
curl -fsS https://$FQDN/healthz        # -> {"status":"ok"}
```

**7. Validate the governed path from a local agent** (this is the M3.3 exit criterion):

```bash
# any MCP client / host: Streamable HTTP url = https://$FQDN/mcp
# Authorization: Bearer dev-token-alice-REPLACE-ME   (image's DEMO identities — smoke only!)
#   -> list tools (demo-files + time), call read_file welcome.txt -> governed + recorded
az containerapp exec -n $APP -g $RG --command "gatekeeper tail"
az containerapp exec -n $APP -g $RG --command "gatekeeper verify"   # OK ledger intact
```

**8. Make it real (before any non-demo use):** mount your own config dir (or bake an image) with:
- `transport.http_allowed_hosts: ["$FQDN", "$FQDN:*"]` — **list it BOTH ways.** The SDK's `:*`
  pattern only matches a Host header that carries a port (`host.startswith(base + ":")`), and a
  request to the HTTPS ingress on :443 sends the host with **no port**, so a `:*`-only entry 421s
  every real request (found on the first live run, 2026-08-24). The `/mcp` DNS-rebinding check refuses unknown
  Host headers with 421 until the public FQDN is allowlisted (deliberate: fail-closed).
- `adapters.identity: oidc` + your Entra tenant per the [OIDC feature doc](../features/oidc-identity.md);
  replace/remove `identities.yaml`. Bearer JWTs remain replayable within their lifetime — keep them
  short-lived; DPoP/mTLS-bound tokens (ADR-006) are the recorded next step if exposure widens.

## Operational notes

- **Updates:** `az acr build … && az containerapp update -n $APP -g $RG --image …` — single
  replica means a brief restart window (accepted: ADR-007 trade; the entrypoint re-runs
  `alembic upgrade head` idempotently).
- **Logs:** structured JSON on stderr → `az containerapp logs show -n $APP -g $RG --follow`
  (SIEM-ready; the ledger remains the authoritative audit record).
- **Cost floor:** 1 always-on small replica (0.25 vCPU / 0.5 Gi) + Standard_LRS file share —
  a few €/month, the cheapest correct shape (consumption-scale-to-zero would cold-start the
  governance hot path and is off by `min-replicas 1`).
- **CI parity:** every push builds this Dockerfile and smoke-checks `/healthz` in the `container`
  CI job, so the image cannot rot between deploys.
