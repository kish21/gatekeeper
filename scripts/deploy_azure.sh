#!/usr/bin/env bash
# Deploy the GateKeeper gateway to Azure Container Apps — one command, safe to re-run.
#
#   bash scripts/deploy_azure.sh
#
# What you need first (the script checks and tells you if something is missing):
#   1. The Azure CLI, signed in:   az login          (install: https://aka.ms/installazurecli)
#   2. This repository checked out; run the script from its root.
#   On Windows, run it from Git Bash.
#
# What it creates on your CURRENT subscription (billable; a few EUR/month):
#   a resource group, a container registry, a Container Apps environment, and one always-on
#   container app (0.25 vCPU / 0.5 GiB) with public HTTPS ingress.
#   Remove everything with:   az group delete -n "${GK_RG:-gatekeeper-rg}" --yes --no-wait
#
# What you get:
#   * a live HTTPS gateway with /healthz, /metrics and the governed /mcp endpoint
#   * the public hostname is trusted automatically (no second build to allow-list it)
#   * fresh, random operator + readonly tokens generated for THIS deployment and stored as a
#     Container Apps secret — the repository's demo tokens are never exposed to the internet
#   * a ready-to-run probe command printed at the end that exercises allow / deny / identity
#
#   * a DURABLE audit ledger on a managed PostgreSQL database: the records survive the replica
#     being replaced, `verify` works from any process, and more than one replica may serve.
#     Already have a database? Set GK_PG_URL to its connection string and no server is created:
#       GK_PG_URL='postgresql://user:pw@host.postgres.database.azure.com:5432/gatekeeper?sslmode=require'
#     Percent-encode a password containing @ : / ? # or & — it is going into a URL.
#   * the approvals desk at /ui, behind its own generated token
#
# What it does NOT give you yet (honest):
#   * corporate login. This deploys with static tokens. Switch to OIDC by setting env vars on the
#     app (GATEKEEPER_IDENTITY=oidc + GATEKEEPER_OIDC_*), no rebuild — see the deploy guide.
#   * anyone being TOLD about a held write, unless you set GK_APPROVAL_WEBHOOK to a Slack/Teams
#     incoming webhook. Without it, an approver has to be watching the desk.
#
# Ledger choice (GK_LEDGER_STORAGE):
#   postgres   (default) a managed PostgreSQL flexible server — durable, multi-replica safe
#   ephemeral            the container's own disk: correct while the replica lives, then gone.
#                        Fine for a throwaway demo, never for anything you must be able to audit.
#   files                Azure Files (SMB). Measured to CORRUPT SQLite (audit.db stayed 0 bytes,
#                        records lost across a restart). Kept only so the finding is reproducible.
#
# Override any name via env: GK_LOCATION GK_RG GK_APP GK_ENV GK_ACR GK_SUFFIX GK_LEDGER_STORAGE
#                            GK_PG_URL GK_PG_SERVER GK_PG_ADMIN GK_REPLICAS GK_APPROVAL_WEBHOOK
set -euo pipefail

# Windows/Git-Bash: keep the Azure CLI's own console output UTF-8 (a cp1252 console otherwise
# kills the CLI on non-ASCII build logs). No-op on Linux/macOS.
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

say()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33mWARNING:\033[0m %s\n' "$*" >&2; }
die()  { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# --- preflight -------------------------------------------------------------------------------
command -v az >/dev/null 2>&1 || die "Azure CLI not found. Install it (https://aka.ms/installazurecli), then 'az login' and re-run."
command -v openssl >/dev/null 2>&1 || die "openssl not found (needed to generate secrets). On Windows, run this from Git Bash."
command -v curl >/dev/null 2>&1 || die "curl not found (needed for the /healthz check)."
[ -f Dockerfile ] || die "Run this from the repository root (Dockerfile not found here)."
az account show >/dev/null 2>&1 || die "Not signed in. Run 'az login' first."
SUB_NAME="$(az account show --query name -o tsv)"
SUB_ID="$(az account show --query id -o tsv)"

# --- names (override via env) ----------------------------------------------------------------
LOCATION="${GK_LOCATION:-westeurope}"
RG="${GK_RG:-gatekeeper-rg}"
APP="${GK_APP:-gatekeeper}"
ENVNAME="${GK_ENV:-gatekeeper-env}"
LEDGER_STORAGE="${GK_LEDGER_STORAGE:-postgres}"   # postgres | ephemeral | files
REPLICAS="${GK_REPLICAS:-1}"                      # >1 is safe ONLY on the postgres ledger
# Registry names must be globally unique + lowercase alphanumeric: derive a deterministic
# per-subscription suffix so re-runs converge on the same resources.
SUFFIX="${GK_SUFFIX:-$(printf '%s' "$SUB_ID" | tr -dc 'a-f0-9' | cut -c1-12)}"
ACR="${GK_ACR:-gkacr${SUFFIX}}"
SA="${GK_SA:-gkled${SUFFIX}}"
SHARE="ledger"
PG_SERVER="${GK_PG_SERVER:-gkpg${SUFFIX}}"
PG_ADMIN="${GK_PG_ADMIN:-gkadmin}"
PG_DB="gatekeeper"
# A unique tag per build: Container Apps compares image references, so re-deploying ':latest'
# is a silent no-op. ':latest' is still pushed as the human-readable pointer.
IMAGE_NAME="gatekeeper"
IMAGE_TAG="$IMAGE_NAME:${GK_IMAGE_TAG:-$(date -u +%Y%m%d%H%M%S)}"

case "$LEDGER_STORAGE" in
  postgres|ephemeral|files) ;;
  *) die "GK_LEDGER_STORAGE must be 'postgres' (default), 'ephemeral', or 'files'." ;;
esac
if [ "$REPLICAS" -gt 1 ] && [ "$LEDGER_STORAGE" != postgres ]; then
  die "GK_REPLICAS=$REPLICAS needs the postgres ledger: two replicas on one SQLite file are two writers on one chain."
fi

cat <<EOF

GateKeeper -> Azure Container Apps
  subscription : ${SUB_NAME} (${SUB_ID})
  location     : ${LOCATION}
  resource grp : ${RG}
  registry     : ${ACR}.azurecr.io
  app          : ${APP}   (${REPLICAS} replica(s), public HTTPS ingress)
  ledger       : ${LEDGER_STORAGE}$(
    case "$LEDGER_STORAGE" in
      postgres)  [ -n "${GK_PG_URL:-}" ] && printf ' (the database you supplied)' || printf " (a managed PostgreSQL server: ${PG_SERVER})" ;;
      ephemeral) printf ' (container disk: LOST on restart — see the header)' ;;
      files)     printf ' (Azure Files SMB: known to corrupt SQLite — see the header)' ;;
    esac)
Press Ctrl-C within 5s to abort.
EOF
sleep 5

# --- 1. resource group + registry; build the image IN Azure (no local Docker needed) ---------
say "1/4 resource group + container registry + image build (a few minutes)"
az group create -n "$RG" -l "$LOCATION" --only-show-errors -o none
az acr create -n "$ACR" -g "$RG" --sku Basic --admin-enabled true --only-show-errors -o none
# Queue the build without streaming its log (the streamer crashes on a Windows console), then
# poll it: a failed build must stop the deploy rather than push a stale image forward.
BUILD_RUN="$(az acr build -r "$ACR" -t "$IMAGE_TAG" -t "$IMAGE_NAME:latest" . --no-logs --query runId -o tsv)"
[ -n "$BUILD_RUN" ] || die "could not queue the image build (no run id returned)."
printf '    build run %s ' "$BUILD_RUN"
BUILD_STATUS=""
for _ in $(seq 1 180); do
  BUILD_STATUS="$(az acr task show-run -r "$ACR" --run-id "$BUILD_RUN" --query status -o tsv 2>/dev/null || echo '')"
  case "$BUILD_STATUS" in Succeeded|Failed|Canceled|Error|Timeout) break ;; esac
  printf '.'; sleep 10
done
printf ' %s\n' "${BUILD_STATUS:-unknown}"
[ "$BUILD_STATUS" = "Succeeded" ] ||
  die "image build ${BUILD_STATUS:-did not finish}. Inspect: az acr task logs -r $ACR --run-id $BUILD_RUN"

# --- 2. Container Apps environment (+ optional Azure Files) ----------------------------------
say "2/4 Container Apps environment"
az extension add -n containerapp --upgrade --only-show-errors -o none
az provider register -n Microsoft.App --only-show-errors -o none 2>/dev/null || true
az provider register -n Microsoft.OperationalInsights --only-show-errors -o none 2>/dev/null || true
[ "$LEDGER_STORAGE" = postgres ] &&
  az provider register -n Microsoft.DBforPostgreSQL --only-show-errors -o none 2>/dev/null || true
az containerapp env create -n "$ENVNAME" -g "$RG" -l "$LOCATION" --only-show-errors -o none

LEDGER_URL=""
if [ "$LEDGER_STORAGE" = postgres ]; then
  if [ -n "${GK_PG_URL:-}" ]; then
    say "2b/4 using the PostgreSQL database you supplied (no server created)"
    LEDGER_URL="$GK_PG_URL"
  else
    say "2b/4 managed PostgreSQL for the audit ledger (a few minutes on a first run)"
    # Burstable B1ms is the cheapest tier that runs this comfortably; the ledger is small and its
    # write rate is one row per governed decision.
    if az postgres flexible-server show -n "$PG_SERVER" -g "$RG" -o none 2>/dev/null; then
      echo "    server $PG_SERVER exists -> keeping it (and its records)"
      PG_PASSWORD="$(az containerapp secret show -n "$APP" -g "$RG" --secret-name ledger-url --query value -o tsv 2>/dev/null || echo '')"
      [ -n "$PG_PASSWORD" ] || die "the server $PG_SERVER exists but this app has no ledger-url secret to reach it with. Pass GK_PG_URL=<connection string> to reuse it."
      LEDGER_URL="$PG_PASSWORD"
    else
      PG_PASSWORD="$(openssl rand -hex 24)"
      az postgres flexible-server create \
        -n "$PG_SERVER" -g "$RG" -l "$LOCATION" \
        --admin-user "$PG_ADMIN" --admin-password "$PG_PASSWORD" \
        --tier Burstable --sku-name Standard_B1ms --storage-size 32 \
        --version 16 --database-name "$PG_DB" \
        --public-access 0.0.0.0 --yes --only-show-errors -o none ||
        die "could not create the PostgreSQL server. Create one yourself and re-run with GK_PG_URL=<connection string>."
      # 0.0.0.0 in Azure's firewall means "Azure services", not "the internet": the container app
      # reaches it, arbitrary hosts do not. To connect from your own machine (psql, a migration,
      # a backup check), add your address:
      #   az postgres flexible-server firewall-rule create -n <server> -g <rg> \
      #     --rule-name me --start-ip-address <your ip> --end-ip-address <your ip>
      LEDGER_URL="postgresql://${PG_ADMIN}:${PG_PASSWORD}@${PG_SERVER}.postgres.database.azure.com:5432/${PG_DB}?sslmode=require"
    fi
  fi
fi

if [ "$LEDGER_STORAGE" = files ]; then
  warn "Azure Files (SMB) does not give SQLite the locking + fsync it needs; measured result: records lost. Proceeding because you asked."
  az storage account create -n "$SA" -g "$RG" -l "$LOCATION" --sku Standard_LRS --only-show-errors -o none
  az storage share-rm create -g "$RG" --storage-account "$SA" -n "$SHARE" --only-show-errors -o none
  SA_KEY="$(az storage account keys list -n "$SA" -g "$RG" --query '[0].value' -o tsv)"
  az containerapp env storage set -n "$ENVNAME" -g "$RG" --storage-name ledger \
    --azure-file-account-name "$SA" --azure-file-account-key "$SA_KEY" \
    --azure-file-share-name "$SHARE" --access-mode ReadWrite --only-show-errors -o none
fi

# --- 3. the app: secrets set ONCE, one replica, public ingress, config via env ---------------
say "3/4 deploy the app"
ACR_LOGIN="$ACR.azurecr.io"
if az containerapp show -n "$APP" -g "$RG" -o none 2>/dev/null; then
  # Re-run: stop-then-start, never a rolling update — two replicas would be two writers on one
  # ledger. The HMAC key + tokens are left untouched so the existing ledger stays verifiable.
  echo "    app exists -> stop-then-start update (secrets kept)"
  OLD_REV="$(az containerapp show -n "$APP" -g "$RG" --query properties.latestRevisionName -o tsv 2>/dev/null || echo '')"
  FQDN_NOW="$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || echo '')"
  if [ -n "$OLD_REV" ]; then
    az containerapp revision deactivate -n "$APP" -g "$RG" --revision "$OLD_REV" --only-show-errors -o none 2>/dev/null ||
      echo "    (could not deactivate $OLD_REV - falling back to a timed drain)"
  fi
  printf '    draining the old replica '
  for _ in $(seq 1 24); do
    if [ -z "$FQDN_NOW" ] || ! curl -fsS --max-time 5 "https://$FQDN_NOW/healthz" >/dev/null 2>&1; then break; fi
    printf '.'; sleep 5
  done
  printf ' stopped\n'
  if [ -n "$LEDGER_URL" ]; then
    az containerapp secret set -n "$APP" -g "$RG" --secrets "ledger-url=$LEDGER_URL" \
      --only-show-errors -o none
    az containerapp update -n "$APP" -g "$RG" \
      --set-env-vars GATEKEEPER_LEDGER_URL=secretref:ledger-url --only-show-errors -o none
  fi
  az containerapp update -n "$APP" -g "$RG" --image "$ACR_LOGIN/$IMAGE_TAG" \
    --min-replicas 1 --max-replicas "$REPLICAS" --only-show-errors -o none
else
  # Fresh tokens for THIS deployment. Stored as a platform secret, never in the image or config.
  OP_TOKEN="$(openssl rand -hex 24)"
  RO_TOKEN="$(openssl rand -hex 24)"
  APPROVER_TOKEN="$(openssl rand -hex 24)"
  UI_TOKEN="$(openssl rand -hex 24)"
  # priya is the approver: she may release held writes at the desk and, having no permit in the
  # Cedar policy, cannot make tool calls of her own.
  IDENTITIES="operator:operator:${OP_TOKEN};readonly:readonly:${RO_TOKEN};priya:approver:${APPROVER_TOKEN}"
  SECRETS=("hmac-key=$(openssl rand -hex 32)" "identities=$IDENTITIES" "ui-token=$UI_TOKEN")
  ENVVARS=(
    GATEKEEPER_HMAC_KEY=secretref:hmac-key
    GATEKEEPER_IDENTITIES=secretref:identities
    GATEKEEPER_UI_TOKEN=secretref:ui-token
  )
  if [ -n "$LEDGER_URL" ]; then
    SECRETS+=("ledger-url=$LEDGER_URL")
    ENVVARS+=(GATEKEEPER_LEDGER_URL=secretref:ledger-url)
  fi
  if [ -n "${GK_APPROVAL_WEBHOOK:-}" ]; then
    SECRETS+=("approval-webhook=${GK_APPROVAL_WEBHOOK}")
    ENVVARS+=(GATEKEEPER_APPROVAL_WEBHOOK=secretref:approval-webhook)
  fi
  az containerapp create -n "$APP" -g "$RG" --environment "$ENVNAME" \
    --registry-server "$ACR_LOGIN" \
    --image "$ACR_LOGIN/$IMAGE_TAG" \
    --target-port 8765 --ingress external \
    --min-replicas 1 --max-replicas "$REPLICAS" \
    --secrets "${SECRETS[@]}" \
    --env-vars "${ENVVARS[@]}" \
    --only-show-errors -o none
fi

if [ "$LEDGER_STORAGE" = files ]; then
  # Mount the share at /data (only the YAML update flow can add a volume). Uses the Azure CLI's
  # own Python (it bundles PyYAML), so nothing extra is needed on the machine.
  PYBIN=""
  for cand in "/opt/az/bin/python3" "/usr/lib/azure-cli/bin/python" \
              "/c/Program Files/Microsoft SDKs/Azure/CLI2/python.exe" \
              "/c/Program Files (x86)/Microsoft SDKs/Azure/CLI2/python.exe" python3 python; do
    if [ -x "$cand" ] || command -v "$cand" >/dev/null 2>&1; then
      if "$cand" -c "import yaml" >/dev/null 2>&1; then PYBIN="$cand"; break; fi
    fi
  done
  [ -n "$PYBIN" ] || die "no Python with PyYAML found to patch the volume mount (install PyYAML or re-run with GK_LEDGER_STORAGE=ephemeral)."
  APP_YAML="$(mktemp).yaml"
  az containerapp show -n "$APP" -g "$RG" -o yaml > "$APP_YAML"
  "$PYBIN" - "$APP_YAML" <<'PY'
import sys, yaml
path = sys.argv[1]
with open(path) as f:
    doc = yaml.safe_load(f)
tpl = doc["properties"]["template"]
vols = tpl.setdefault("volumes", []) or []
if not any((v or {}).get("name") == "ledger" for v in vols):
    vols.append({"name": "ledger", "storageName": "ledger", "storageType": "AzureFile"})
tpl["volumes"] = vols
for c in tpl.get("containers", []):
    mounts = c.setdefault("volumeMounts", []) or []
    if not any((m or {}).get("volumeName") == "ledger" for m in mounts):
        mounts.append({"volumeName": "ledger", "mountPath": "/data"})
    c["volumeMounts"] = mounts
with open(path, "w") as f:
    yaml.safe_dump(doc, f, sort_keys=False)
PY
  az containerapp update -n "$APP" -g "$RG" --yaml "$APP_YAML" --only-show-errors -o none
  rm -f "$APP_YAML"
fi

# --- 4. wait for liveness + report ----------------------------------------------------------
say "4/4 wait for /healthz"
FQDN="$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
OK=0
for _ in $(seq 1 40); do
  if curl -fsS "https://$FQDN/healthz" >/dev/null 2>&1; then OK=1; break; fi
  sleep 3
done
[ "$OK" = 1 ] || die "/healthz never came up. Inspect: az containerapp logs show -n $APP -g $RG --follow"

# The desk's own URL goes into the held-write notifications, so a message is one click from a
# decision. Only knowable after the ingress exists, so it is set here — once.
DESK_URL="https://${FQDN}/ui"
CURRENT_DESK="$(az containerapp show -n "$APP" -g "$RG" --query "properties.template.containers[0].env[?name=='GATEKEEPER_DESK_URL'].value | [0]" -o tsv 2>/dev/null || echo '')"
if [ "$CURRENT_DESK" != "$DESK_URL" ]; then
  az containerapp update -n "$APP" -g "$RG" \
    --set-env-vars "GATEKEEPER_DESK_URL=$DESK_URL" --only-show-errors -o none
fi

printf '\n\033[1;32mDEPLOYED.\033[0m  https://%s\n' "$FQDN"
cat <<EOF

Prove it governs AND that the audit trail is durable — from this machine, over the internet:
  IDS=\$(az containerapp secret show -n ${APP} -g ${RG} --secret-name identities --query value -o tsv)
  UIT=\$(az containerapp secret show -n ${APP} -g ${RG} --secret-name ui-token --query value -o tsv)
  python -m scripts.probe_hosted --url "https://${FQDN}" \\
    --operator-token "\$(echo "\$IDS" | cut -d';' -f1 | cut -d: -f3)" \\
    --readonly-token "\$(echo "\$IDS" | cut -d';' -f2 | cut -d: -f3)" \\
    --ui-token "\$UIT"

Then restart the app and run the SAME probe with --expect-at-least <the number it just reported>.
The records must still be there; that is the check the first Azure run failed:
  az containerapp revision restart -n ${APP} -g ${RG} --revision "\$(az containerapp show -n ${APP} -g ${RG} --query properties.latestRevisionName -o tsv)"

The desk (approvals, activity, the integrity check, the governed servers):
  ${DESK_URL}       sign in with the approver token:
  echo "\$IDS" | cut -d';' -f3 | cut -d: -f3

Look at the audit trail inside the running container:
  az containerapp exec -n ${APP} -g ${RG} --command "gatekeeper tail --with-id"
  az containerapp exec -n ${APP} -g ${RG} --command "gatekeeper verify"
Live metrics:  curl https://${FQDN}/metrics

Switch to your corporate login (no rebuild):
  az containerapp update -n ${APP} -g ${RG} --set-env-vars GATEKEEPER_IDENTITY=oidc \\
    GATEKEEPER_OIDC_ISSUER=<issuer> GATEKEEPER_OIDC_AUDIENCE=<audience> \\
    GATEKEEPER_OIDC_GROUP_ROLE_MAP="<group-id>=operator,<group-id>=readonly"

Tear everything down:
  az group delete -n ${RG} --yes --no-wait
EOF
