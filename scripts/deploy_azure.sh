#!/usr/bin/env bash
# One-shot deploy of the GateKeeper gateway to Azure Container Apps (M3.3).
#
# Encodes docs/deploy/azure-container-apps.md as an IDEMPOTENT script: safe to re-run, it converges
# to the same resources. The image bakes its own HTTP config (deploy/container/platform.yaml binds
# 0.0.0.0:8765 with the ADR-009 ack, ledger at /data/audit.db), so the only runtime secret is the
# HMAC key — created ONCE and kept stable across re-runs (changing it would break the existing
# hash-chained ledger's `verify`).
#
# PREREQUISITES (yours — this script does NOT do them):
#   1. Install the Azure CLI:  winget install -e --id Microsoft.AzureCLI   (then restart the shell)
#   2. Sign in:                az login
#   3. Pick the subscription:  az account set --subscription "<name-or-id>"   (optional)
#   Run from the repo root:    bash scripts/deploy_azure.sh
#
# COST: this CREATES BILLABLE resources on your *current* subscription — a 0.25 vCPU/0.5Gi container
# app (1 always-on replica) + a Standard_LRS file share, ~a few EUR/month. Remove everything with:
#   az group delete -n "${GK_RG:-gatekeeper-rg}" --yes --no-wait
#
# HONEST NOTE: this is the FIRST live run of this path (the Azure proof was previously docs-only).
# It gets you to: a live HTTPS gateway, /healthz green, ledger on persistent storage, `verify` clean.
# The EXTERNAL governed /mcp call + real OIDC are the documented "make it real" follow-ups printed at
# the end (they need the public FQDN allow-listed in the image config + your IdP tenant).
#
# Override any name via env: GK_LOCATION GK_RG GK_APP GK_ENV GK_SHARE GK_ACR GK_SA GK_SUFFIX
set -euo pipefail

say() { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# --- preflight -------------------------------------------------------------------------------
command -v az  >/dev/null 2>&1 || die "Azure CLI not found. Install it (see the header) and re-run."
command -v openssl >/dev/null 2>&1 || die "openssl not found (needed to generate the HMAC key)."
command -v curl >/dev/null 2>&1 || die "curl not found (needed for the /healthz smoke test)."
[ -f Dockerfile ] || die "Run this from the repo root (Dockerfile not found here)."

az account show >/dev/null 2>&1 || die "Not signed in. Run 'az login' first."
SUB_NAME="$(az account show --query name -o tsv)"
SUB_ID="$(az account show --query id -o tsv)"

# --- config (override via env) ---------------------------------------------------------------
LOCATION="${GK_LOCATION:-westeurope}"
RG="${GK_RG:-gatekeeper-rg}"
APP="${GK_APP:-gatekeeper}"
ENVNAME="${GK_ENV:-gatekeeper-env}"
SHARE="${GK_SHARE:-ledger}"
# ACR + storage names must be globally unique + lowercase alphanumeric. Derive a DETERMINISTIC
# per-subscription suffix so re-runs hit the same resources (idempotent), unless overridden.
SUFFIX="${GK_SUFFIX:-$(printf '%s' "$SUB_ID" | tr -dc 'a-f0-9' | cut -c1-12)}"
ACR="${GK_ACR:-gkacr${SUFFIX}}"
SA="${GK_SA:-gkled${SUFFIX}}"
IMAGE_TAG="gatekeeper:latest"

cat <<EOF

GateKeeper -> Azure Container Apps
  subscription : ${SUB_NAME} (${SUB_ID})
  location     : ${LOCATION}
  resource grp : ${RG}
  registry     : ${ACR}.azurecr.io
  app          : ${APP}   (1 replica, external HTTPS ingress)
  ledger store : ${SA} / file share '${SHARE}' -> /data
Press Ctrl-C within 5s to abort.
EOF
sleep 5

# --- 1. resource group + registry; build the image IN Azure (no local Docker needed) ---------
say "1/6 resource group + container registry + image build (this can take a few minutes)"
az group create -n "$RG" -l "$LOCATION" --only-show-errors -o none
az acr create -n "$ACR" -g "$RG" --sku Basic --admin-enabled true --only-show-errors -o none
az acr build -r "$ACR" -t "$IMAGE_TAG" .

# --- 2. Container Apps environment -----------------------------------------------------------
say "2/6 Container Apps environment"
az extension add -n containerapp --upgrade --only-show-errors -o none
az provider register -n Microsoft.App --only-show-errors -o none 2>/dev/null || true
az provider register -n Microsoft.OperationalInsights --only-show-errors -o none 2>/dev/null || true
az containerapp env create -n "$ENVNAME" -g "$RG" -l "$LOCATION" --only-show-errors -o none

# --- 3. persistent ledger storage (Azure Files -> /data) -------------------------------------
say "3/6 persistent ledger storage (Azure Files)"
az storage account create -n "$SA" -g "$RG" -l "$LOCATION" --sku Standard_LRS --only-show-errors -o none
az storage share-rm create --storage-account "$SA" -n "$SHARE" --only-show-errors -o none
SA_KEY="$(az storage account keys list -n "$SA" -g "$RG" --query '[0].value' -o tsv)"
az containerapp env storage set -n "$ENVNAME" -g "$RG" --storage-name ledger \
  --azure-file-account-name "$SA" --azure-file-account-key "$SA_KEY" \
  --azure-file-share-name "$SHARE" --access-mode ReadWrite --only-show-errors -o none

# --- 4. deploy the app (1 replica = ADR-007; secret HMAC key set ONCE; external HTTPS) --------
say "4/6 deploy the app"
ACR_LOGIN="$ACR.azurecr.io"
if az containerapp show -n "$APP" -g "$RG" -o none 2>/dev/null; then
  # Re-run: update the image only. The HMAC secret is left UNTOUCHED so the existing ledger on the
  # volume stays verifiable (a new key would break the hash-chain's `verify`).
  echo "    app exists -> updating image (keeping the existing HMAC key + ledger)"
  az containerapp update -n "$APP" -g "$RG" --image "$ACR_LOGIN/$IMAGE_TAG" --only-show-errors -o none
else
  az containerapp create -n "$APP" -g "$RG" --environment "$ENVNAME" \
    --registry-server "$ACR_LOGIN" \
    --image "$ACR_LOGIN/$IMAGE_TAG" \
    --target-port 8765 --ingress external \
    --min-replicas 1 --max-replicas 1 \
    --secrets "hmac-key=$(openssl rand -hex 32)" \
    --env-vars GATEKEEPER_HMAC_KEY=secretref:hmac-key --only-show-errors -o none
fi

# --- 5. mount the ledger volume at /data (idempotent YAML patch) ------------------------------
say "5/6 mount the ledger volume at /data"
PYBIN=""
for cand in python3 python ./.venv/Scripts/python.exe; do
  if "$cand" -c "import yaml" >/dev/null 2>&1; then PYBIN="$cand"; break; fi
done
if [ -z "$PYBIN" ]; then
  cat <<'EOF'
    SKIPPED: no Python with PyYAML found to patch the volume mount automatically.
    Do it manually (one time):
      az containerapp show -n <app> -g <rg> -o yaml > app.yaml
      # under properties.template add:    volumes: [{name: ledger, storageName: ledger, storageType: AzureFile}]
      # under the container add:          volumeMounts: [{volumeName: ledger, mountPath: /data}]
      az containerapp update -n <app> -g <rg> --yaml app.yaml && rm app.yaml
EOF
else
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

# --- 6. wait for liveness + report -----------------------------------------------------------
say "6/6 wait for /healthz"
FQDN="$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
OK=0
for _ in $(seq 1 40); do
  if curl -fsS "https://$FQDN/healthz" >/dev/null 2>&1; then OK=1; break; fi
  sleep 3
done
[ "$OK" = 1 ] || die "/healthz never came up. Inspect: az containerapp logs show -n $APP -g $RG --follow"

printf '\n\033[1;32mDEPLOYED.\033[0m  https://%s/healthz -> ok   (gateway live, ledger on the Azure Files volume)\n' "$FQDN"
cat <<EOF

Verify the audit ledger inside the running container (interactive):
  az containerapp exec -n ${APP} -g ${RG} --command "gatekeeper verify"     # -> OK ledger intact
  az containerapp exec -n ${APP} -g ${RG} --command "gatekeeper tail"
Live metrics:
  curl https://${FQDN}/metrics

MAKE IT REAL (before any non-demo use) — see docs/deploy/azure-container-apps.md step 8:
  * Allow-list the public host so external /mcp calls pass the DNS-rebinding check:
      set transport.http_allowed_hosts: ["${FQDN}:*"] in the image config and re-deploy.
  * Switch identity from the demo static tokens to OIDC (your Entra/Okta tenant):
      docs/features/oidc-identity.md  (adapters.identity: oidc + your tenant).

Tear everything down:
  az group delete -n ${RG} --yes --no-wait
EOF
