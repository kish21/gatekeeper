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

About fifteen minutes. It creates a resource group, a container registry (the image is built in
Azure, no local Docker needed), a Container Apps environment, a **managed PostgreSQL server for the
audit ledger**, and one always-on container app with public HTTPS ingress. It is safe to re-run:
names are deterministic, the image gets a fresh tag each time, and the secrets — including the
database — are created once and kept.

**Already have a database?** `GK_PG_URL='postgresql://user:pw@host:5432/db?sslmode=require' bash
scripts/deploy_azure.sh` uses it and creates no server.

What you get, with no further steps:

- **A durable audit trail.** The ledger is in the database, not on the container's disk, so it
  survives the replica being replaced, `verify` works from any process, and you can run more than
  one replica (`GK_REPLICAS=2`).
- The public hostname is trusted automatically. Azure injects it into the container and the
  gateway allow-lists it at boot, so there is no rebuild to add it.
- Fresh operator, read-only and **approver** tokens generated for this deployment, plus a desk
  token, all stored as Container Apps secrets. The repository's demo tokens are never on the
  internet; the gateway refuses to serve them on a public interface.
- **The desk at `/ui`**, where a signed-in approver — and only an approver, and never the person
  who made the call — releases held writes.
- The ledger schema is created on first boot.

Set `GK_APPROVAL_WEBHOOK` to a Slack or Teams incoming webhook before you run it, and held writes
are announced there with a link straight to the desk. Without it, somebody has to be watching.

The script ends by printing the exact commands for the next section.

## Prove it governs

From your machine, over the public internet:

```bash
IDS=$(az containerapp secret show -n gatekeeper -g gatekeeper-rg --secret-name identities --query value -o tsv)
UIT=$(az containerapp secret show -n gatekeeper -g gatekeeper-rg --secret-name ui-token --query value -o tsv)
python -m scripts.probe_hosted --url "https://<fqdn>" \
  --operator-token "$(echo "$IDS" | cut -d';' -f1 | cut -d: -f3)" \
  --readonly-token "$(echo "$IDS" | cut -d';' -f2 | cut -d: -f3)" \
  --ui-token "$UIT"
```

The probe reports one line per check: reachable over HTTPS, an operator read allowed, a read-only
write denied by policy, an unknown token denied, `/metrics` live, and — the two that used to fail —
the ledger read back and verified **from a second process**. It keeps "allowed", "denied", and
"error" distinct, so a broken connection can never score as a passing deny.

Then prove the records survive the thing that used to lose them. Restart the app and run the same
probe again, telling it how many calls it should still find:

```bash
az containerapp revision restart -n gatekeeper -g gatekeeper-rg \
  --revision "$(az containerapp show -n gatekeeper -g gatekeeper-rg --query properties.latestRevisionName -o tsv)"
python -m scripts.probe_hosted --url "https://<fqdn>" ... --ui-token "$UIT" --expect-at-least 4
```

Inside the running container:

```bash
az containerapp exec -n gatekeeper -g gatekeeper-rg --command "gatekeeper tail --with-id"
az containerapp exec -n gatekeeper -g gatekeeper-rg --command "gatekeeper verify"
```

An operator's write on the hosted gateway waits for a person just as it does locally. The desk is
at `https://<fqdn>/ui`; the deploy script sets its token for you. Sign in there with the
**approver** token (the third entry in the `identities` secret) and the decision is recorded under
that proven name — a name typed into the page is refused on a public bind, the person who made the
call cannot approve it, and only the roles in `product.yaml` `approval.approver_roles` may decide.

From a terminal on the host: `az containerapp exec ... --command "gatekeeper pending"` then
`... "gatekeeper approve <id>"`; those are recorded as `console` decisions, and can be switched off
entirely with `approval.console_approvals: false`. `GATEKEEPER_APPROVAL_WRITES=off` lets writes
through without a person.

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
| `GATEKEEPER_LEDGER_URL` | **The durable ledger**: a Postgres connection string. Set by the deploy script; overrides the file below |
| `GATEKEEPER_LEDGER_PATH` | Where the SQLite ledger file lives when no URL is set. The image sets `/data/audit.db` |
| `GATEKEEPER_HMAC_KEY_PREVIOUS` | Retired chain keys, comma-separated, so records written before a rotation still verify |
| `GATEKEEPER_APPROVAL_WEBHOOK` | Slack/Teams incoming webhook: where held writes are announced |
| `GATEKEEPER_DESK_URL` | The desk's public URL, put into those messages |
| `GATEKEEPER_UI_TOKEN` | Required to serve the desk at `/ui` beyond loopback; unset = no UI on a public bind |
| `GATEKEEPER_APPROVAL_WRITES` | `require` (default) holds operator writes for a human; `off` lets them through |
| `GATEKEEPER_APPROVAL_TIMEOUT_S` | Seconds a held write waits before it counts as denied (90) |
| `GATEKEEPER_ALLOW_DEMO_TOKENS` | `1` permits the repository's placeholder tokens on a public bind. Smoke tests only |

Mount your own `config/` over `/app/config` (or point `GATEKEEPER_CONFIG_DIR` at it) to change the
governed servers or the policy.

## The ledger, and what used to be wrong with it

The first live run of this deployment proved governance over the public internet and **disproved**
the durable audit trail. On Azure Files (SMB) the SQLite database stayed at zero bytes while calls
were served, a second process reported "Ledger table not found", and a restart lost every record —
SMB does not give SQLite the locking and honest `fsync` it depends on. On the container's own disk
the records were correct, and died with the replica.

That is fixed by putting the ledger in a managed **PostgreSQL** database, which is now the default
(`GK_LEDGER_STORAGE=postgres`). Appends serialize on a transaction-scoped advisory lock, so the
hash chain stays single even with several replicas writing; the records outlive any container; and
`verify` works from your laptop, the desk, or a second process, because the data is not in a file
one container owns. See [the feature doc](../features/durable-ledger.md) for how it is tested —
including six concurrent writers producing one intact chain.

Two options remain for people who want them, both with their eyes open:

| `GK_LEDGER_STORAGE` | What you get |
|---|---|
| `postgres` (default) | Durable, multi-replica safe. A Burstable B1ms server, a few euros a month |
| `ephemeral` | The container's own disk. Correct while the replica lives, then gone. A throwaway demo only |
| `files` | Azure Files (SMB). **Measured to corrupt SQLite.** Kept so the finding stays reproducible |

`GK_REPLICAS=2` is refused unless the ledger is Postgres: two replicas on one SQLite file are two
writers on one chain.

## Keeping the record over time

```bash
az containerapp exec -n gatekeeper -g gatekeeper-rg --command "gatekeeper export --format cef --since 2026-01-01"
az containerapp exec -n gatekeeper -g gatekeeper-rg --command "gatekeeper verify --json"
```

Retention (`gatekeeper archive --before <date> --out <file> --prune`) removes old records under a
signed checkpoint that `verify` resumes from, so trimming the ledger never makes a deletion
undetectable. Rotating the chain key (`gatekeeper rotate-key`) keeps every existing record
verifiable. Both are in [ledger operations](../features/ledger-operations.md) — and note that
`exec` writes to the container's own disk, so copy anything you archive off it.

## Operations

- **Updates:** re-run the script. It drains the old revision before starting the new one — no
  longer strictly necessary on the Postgres ledger, which is safe with concurrent writers, but it
  keeps a re-run behaving the same way on every storage option.
- **Logs:** `az containerapp logs show -n gatekeeper -g gatekeeper-rg --follow` (structured JSON).
- **Metrics:** `https://<fqdn>/metrics` in Prometheus text format.
- **Cost:** one small always-on replica, a Basic registry, and a Burstable B1ms Postgres server —
  roughly €20-30 a month at the time of writing. `GK_LEDGER_STORAGE=ephemeral` drops the database
  (and the durability).
- **Backups:** the ledger is now an ordinary managed database. Azure's automatic backups cover it;
  set the retention your audit policy requires.
- **Tear down:** `az group delete -n gatekeeper-rg --yes --no-wait`.

Override any resource name with `GK_RG`, `GK_APP`, `GK_LOCATION`, `GK_ENV`, `GK_ACR`, `GK_SUFFIX`,
`GK_PG_SERVER`, `GK_PG_ADMIN`. Bring your own database with `GK_PG_URL`, scale with `GK_REPLICAS`,
and announce held writes with `GK_APPROVAL_WEBHOOK`.
