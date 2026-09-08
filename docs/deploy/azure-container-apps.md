# Deploy to Azure Container Apps

One command deploys the gateway as a container behind Azure's HTTPS ingress. The container is
cloud-neutral (see the `Dockerfile`); Azure is the documented path.

## What you need

- The Azure CLI, signed in (`az login`). On Windows, run the script from Git Bash.
- This repository checked out. Run the script from its root.

## Deploy

```bash
bash scripts/deploy_azure.sh
```

About ten minutes. It creates a resource group, a container registry (the image is built in
Azure, no local Docker needed), a Container Apps environment, and one always-on container app
with public HTTPS ingress. It is safe to re-run: names are deterministic, the image gets a fresh
tag each time, and the secrets are created once and kept.

What you get, with no further steps:

- The public hostname is trusted automatically. Azure injects it into the container and the
  gateway allow-lists it at boot, so there is no rebuild to add it.
- Fresh operator and read-only tokens are generated for this deployment and stored as a
  Container Apps secret. The repository's demo tokens are never on the internet; the gateway
  refuses to serve them on a public interface.
- The ledger schema is created on first boot.

The script ends by printing the exact commands for the next section.

## Prove it governs

From your machine, over the public internet:

```bash
IDS=$(az containerapp secret show -n gatekeeper -g gatekeeper-rg --secret-name identities --query value -o tsv)
python -m scripts.probe_hosted --url "https://<fqdn>" \
  --operator-token "$(echo "$IDS" | cut -d';' -f1 | cut -d: -f3)" \
  --readonly-token "$(echo "$IDS" | cut -d';' -f2 | cut -d: -f3)"
```

The probe reports one line per check: reachable over HTTPS, an operator read allowed, a read-only
write denied by policy, an unknown token denied, and `/metrics` live. It keeps "allowed",
"denied", and "error" distinct, so a broken connection can never score as a passing deny.

Inside the running container:

```bash
az containerapp exec -n gatekeeper -g gatekeeper-rg --command "gatekeeper tail --with-id"
az containerapp exec -n gatekeeper -g gatekeeper-rg --command "gatekeeper verify"
```

An operator's write on the hosted gateway waits for a person just as it does locally. The desk
is served at `https://<fqdn>/ui` once `GATEKEEPER_UI_TOKEN` is set on the app (the page asks for
it once); without a token the UI is not mounted on a public bind. From a terminal:
`az containerapp exec ... --command "gatekeeper pending"` then `... "gatekeeper approve <id>"`.
Set `GATEKEEPER_APPROVAL_WRITES=off` to let writes through without a person.

## Switch to your corporate login

No rebuild. Set the OIDC variables on the app and it restarts with per-request token validation
against your identity provider's public keys:

```bash
az containerapp update -n gatekeeper -g gatekeeper-rg --set-env-vars \
  GATEKEEPER_IDENTITY=oidc \
  GATEKEEPER_OIDC_ISSUER="https://login.microsoftonline.com/<tenant-id>/v2.0" \
  GATEKEEPER_OIDC_AUDIENCE="<client-id or api://... identifier>" \
  GATEKEEPER_OIDC_GROUP_ROLE_MAP="<group-object-id>=operator,<group-object-id>=readonly"
```

Registering the app and the groups in Entra ID is covered in the
[OIDC feature doc](../features/oidc-identity.md). An unmapped group is denied; there is no
default role.

## Every knob is an environment variable

| Variable | Meaning |
|---|---|
| `GATEKEEPER_HMAC_KEY` | Required. The ledger's chain key. Set once; changing it makes old entries unverifiable |
| `GATEKEEPER_IDENTITIES` | `principal:role:token;...` — this deployment's static tokens |
| `GATEKEEPER_IDENTITY` | `static_token` or `oidc` |
| `GATEKEEPER_OIDC_*` | Issuer, audience, group-to-role map, optional JWKS URL and claim names |
| `GATEKEEPER_HTTP_ALLOWED_HOSTS` | Extra public hostnames, comma-separated. Not needed on Azure |
| `GATEKEEPER_LEDGER_PATH` | Where the ledger file lives. The image sets `/data/audit.db` |
| `GATEKEEPER_UI_TOKEN` | Required to serve the desk at `/ui` beyond loopback; unset = no UI on a public bind |
| `GATEKEEPER_APPROVAL_WRITES` | `require` (default) holds operator writes for a human; `off` lets them through |
| `GATEKEEPER_APPROVAL_TIMEOUT_S` | Seconds a held write waits before it counts as denied (90) |
| `GATEKEEPER_ALLOW_DEMO_TOKENS` | `1` permits the repository's placeholder tokens on a public bind. Smoke tests only |

Mount your own `config/` over `/app/config` (or point `GATEKEEPER_CONFIG_DIR` at it) to change the
governed servers or the policy.

## What is not durable yet

**The hosted audit ledger does not survive a replica restart.** By default the ledger lives on the
container's own disk. It is correct and tamper-evident while the replica runs, and it is gone when
Azure replaces the replica.

Azure Files over SMB was the first attempt at persistence and it does not work for SQLite: on a
live run the database file stayed at zero bytes while calls were served, a second process could
not read it, and a restart lost every record. SMB does not provide the locking and honest `fsync`
SQLite depends on. The script keeps that option behind `GK_LEDGER_STORAGE=files` with a warning,
for anyone who wants to reproduce the finding.

The fix is a design decision, tracked as a follow-up:

1. Azure Files over NFS 4.1 (Premium tier, VNet-integrated environment). Keeps SQLite.
2. A Postgres ledger behind the existing ledger port. The bigger change, and the one that also
   allows more than one replica.

Until one lands, treat the hosted deployment as proof of governance over the public internet, not
as a durable audit store.

## Operations

- **Updates:** re-run the script. It deactivates the old revision and waits for it to drain
  before starting the new one, so there is never a second writer on the ledger.
- **Logs:** `az containerapp logs show -n gatekeeper -g gatekeeper-rg --follow` (structured JSON).
- **Metrics:** `https://<fqdn>/metrics` in Prometheus text format.
- **Cost:** one small always-on replica plus a Basic registry, a few euros a month.
- **Tear down:** `az group delete -n gatekeeper-rg --yes --no-wait`.

Override any resource name with `GK_RG`, `GK_APP`, `GK_LOCATION`, `GK_ENV`, `GK_ACR`, `GK_SUFFIX`.
