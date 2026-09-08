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
# What it does NOT give you yet (honest):
#   * a DURABLE audit ledger. By default the ledger lives on the container's own disk: correct
#     and tamper-evident while the replica runs, lost when it restarts. Azure Files (SMB) was
#     measured to corrupt SQLite (audit.db stayed 0 bytes, records lost), so it is NOT the default;
#     GK_LEDGER_STORAGE=files provisions it anyway if you want to try. Durable hosted audit
#     (Postgres ledger or an NFS share) is the tracked follow-up — see docs/deploy/azure-container-apps.md.
#   * corporate login. This deploys with static tokens. Switch to OIDC by setting env vars on the
#     app (GATEKEEPER_IDENTITY=oidc + GATEKEEPER_OIDC_*), no rebuild — see the deploy guide.
#
# Override any name via env: GK_LOCATION GK_RG GK_APP GK_ENV GK_ACR GK_SUFFIX GK_LEDGER_STORAGE
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
LEDGER_STORAGE="${GK_LEDGER_STORAGE:-ephemeral}"   # ephemeral | files
# Registry names must be globally unique + lowercase alphanumeric: derive a deterministic
# per-subscription suffix so re-runs converge on the same resources.
SUFFIX="${GK_SUFFIX:-$(printf '%s' "$SUB_ID" | tr -dc 'a-f0-9' | cut -c1-12)}"
ACR="${GK_ACR:-gkacr${SUFFIX}}"
SA="${GK_SA:-gkled${SUFFIX}}"
SHARE="ledger"
# A unique tag per build: Container Apps compares image references, so re-deploying ':latest'
# is a silent no-op. ':latest' is still pushed as the human-readable pointer.
IMAGE_NAME="gatekeeper"
IMAGE_TAG="$IMAGE_NAME:${GK_IMAGE_TAG:-$(date -u +%Y%m%d%H%M%S)}"

case "$LEDGER_STORAGE" in
  ephemeral|files) ;;
  *) die "GK_LEDGER_STORAGE must be 'ephemeral' (default) or 'files'." ;;
esac

cat <<EOF

GateKeeper -> Azure Container Apps
  subscription : ${SUB_NAME} (${SUB_ID})
  location     : ${LOCATION}
  resource grp : ${RG}
  registry     : ${ACR}.azurecr.io
  app          : ${APP}   (1 replica, public HTTPS ingress)
  ledger       : ${LEDGER_STORAGE}$( [ "$LEDGER_STORAGE" = ephemeral ] && printf ' (container disk: lost on restart — see the header)' || printf ' (Azure Files SMB: known to corrupt SQLite — see the header)')
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
az containerapp env create -n "$ENVNAME" -g "$RG" -l "$LOCATION" --only-show-errors -o none

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
  az containerapp update -n "$APP" -g "$RG" --image "$ACR_LOGIN/$IMAGE_TAG" \
    --min-replicas 1 --max-replicas 1 --only-show-errors -o none
else
  # Fresh tokens for THIS deployment. Stored as a platform secret, never in the image or config.
  OP_TOKEN="$(openssl rand -hex 24)"
  RO_TOKEN="$(openssl rand -hex 24)"
  IDENTITIES="operator:operator:${OP_TOKEN};readonly:readonly:${RO_TOKEN}"
  az containerapp create -n "$APP" -g "$RG" --environment "$ENVNAME" \
    --registry-server "$ACR_LOGIN" \
    --image "$ACR_LOGIN/$IMAGE_TAG" \
    --target-port 8765 --ingress external \
    --min-replicas 1 --max-replicas 1 \
    --secrets "hmac-key=$(openssl rand -hex 32)" "identities=$IDENTITIES" \
    --env-vars GATEKEEPER_HMAC_KEY=secretref:hmac-key GATEKEEPER_IDENTITIES=secretref:identities \
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

printf '\n\033[1;32mDEPLOYED.\033[0m  https://%s\n' "$FQDN"
cat <<EOF

Prove it governs, from this machine over the public internet (allow, policy deny, identity deny):
  IDS=\$(az containerapp secret show -n ${APP} -g ${RG} --secret-name identities --query value -o tsv)
  python -m scripts.probe_hosted --url "https://${FQDN}" \\
    --operator-token "\$(echo "\$IDS" | cut -d';' -f1 | cut -d: -f3)" \\
    --readonly-token "\$(echo "\$IDS" | cut -d';' -f2 | cut -d: -f3)"

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
