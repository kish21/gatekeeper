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

# Windows/Git-Bash: the Azure CLI streams the ACR build log through a cp1252 console and dies with
# `UnicodeEncodeError: 'charmap' codec can't encode` on pip's non-ASCII output — the SERVER-side
# build keeps running, only the local CLI crashes (observed on the first live run, 2026-08-24).
# Forcing UTF-8 on the CLI's own stdio fixes it and is a no-op on Linux/macOS.
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

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
# A UNIQUE tag per build. Deploying `:latest` twice is a no-op: Container Apps compares the image
# REFERENCE, sees an identical string, and keeps the running revision — so a rebuilt image is
# silently ignored and the old code keeps serving (cost us the 421 on the first live run, when the
# FQDN allow-list never reached the container). A changing tag forces a new revision, always.
# `:latest` is still pushed alongside, as the human-readable "what is current" pointer.
IMAGE_NAME="gatekeeper"
IMAGE_VERSION="${GK_IMAGE_TAG:-$(date -u +%Y%m%d%H%M%S)}"
IMAGE_TAG="$IMAGE_NAME:$IMAGE_VERSION"

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
# Queue the build WITHOUT streaming its log. The CLI's streamer renders the log through colorama
# into the local console; on Windows (cp1252) pip's non-ASCII output kills the CLI with
# `UnicodeEncodeError: 'charmap' codec can't encode` while the server-side build carries on happily
# (observed twice on the first live run, 2026-08-24; PYTHONIOENCODING alone does NOT fix it).
# --no-logs sidesteps the streamer entirely, so we poll the run instead: a failed build must still
# stop the deploy rather than push a stale image forward.
BUILD_RUN="$(az acr build -r "$ACR" -t "$IMAGE_TAG" -t "$IMAGE_NAME:latest" . --no-logs --query runId -o tsv)"
[ -n "$BUILD_RUN" ] || die "could not queue the image build (no run id returned)."
printf '    build run %s (logs: az acr task logs -r %s --run-id %s) ' "$BUILD_RUN" "$ACR" "$BUILD_RUN"
BUILD_STATUS=""
for _ in $(seq 1 180); do
  BUILD_STATUS="$(az acr task show-run -r "$ACR" --run-id "$BUILD_RUN" --query status -o tsv 2>/dev/null || echo '')"
  case "$BUILD_STATUS" in
    Succeeded|Failed|Canceled|Error|Timeout) break ;;
  esac
  printf '.'
  sleep 10
done
printf ' %s\n' "${BUILD_STATUS:-unknown}"
[ "$BUILD_STATUS" = "Succeeded" ] ||
  die "image build ${BUILD_STATUS:-did not finish}. Inspect: az acr task logs -r $ACR --run-id $BUILD_RUN"

# --- 2. Container Apps environment -----------------------------------------------------------
say "2/6 Container Apps environment"
az extension add -n containerapp --upgrade --only-show-errors -o none
az provider register -n Microsoft.App --only-show-errors -o none 2>/dev/null || true
az provider register -n Microsoft.OperationalInsights --only-show-errors -o none 2>/dev/null || true
az containerapp env create -n "$ENVNAME" -g "$RG" -l "$LOCATION" --only-show-errors -o none

# --- 3. persistent ledger storage (Azure Files -> /data) -------------------------------------
say "3/6 persistent ledger storage (Azure Files)"
az storage account create -n "$SA" -g "$RG" -l "$LOCATION" --sku Standard_LRS --only-show-errors -o none
# -g is REQUIRED here: given a bare account NAME (not a resource id), the CLI cannot construct the
# id without the group and fails with "argument 'resource_group' is not defined" (first live run).
az storage share-rm create -g "$RG" --storage-account "$SA" -n "$SHARE" --only-show-errors -o none
SA_KEY="$(az storage account keys list -n "$SA" -g "$RG" --query '[0].value' -o tsv)"
az containerapp env storage set -n "$ENVNAME" -g "$RG" --storage-name ledger \
  --azure-file-account-name "$SA" --azure-file-account-key "$SA_KEY" \
  --azure-file-share-name "$SHARE" --access-mode ReadWrite --only-show-errors -o none

# --- 4. deploy the app (1 replica = ADR-007; secret HMAC key set ONCE; external HTTPS) --------
say "4/6 deploy the app"
ACR_LOGIN="$ACR.azurecr.io"
if az containerapp show -n "$APP" -g "$RG" -o none 2>/dev/null; then
  # Re-run: STOP-THEN-START, never a rolling update. The HMAC secret is left UNTOUCHED so the
  # existing ledger on the volume stays verifiable (a new key would break the hash-chain's `verify`).
  #
  # WHY NOT A PLAIN `update --image`: Container Apps rolls revisions — it starts the NEW replica
  # while the OLD one is still running. Both mount the same Azure Files ledger, so for those seconds
  # there are TWO writers, which ADR-007 forbids "by construction". Observed on the first live run
  # (2026-08-24): the new revision died in `alembic upgrade head` with
  # `sqlite3.OperationalError: database is locked`, the old revision kept serving the STALE config,
  # and every redeploy silently no-oped. SQLite refusing was the good outcome; a silent second
  # writer would corrupt the hash chain. Scaling to zero first makes the single-writer invariant
  # true across deploys too, at the cost of a short outage (ADR-007 already accepts a restart gap).
  # `--max-replicas 0` is rejected (Azure requires [1,1000]) and there is no `containerapp stop` in
  # every CLI version, so the old writer is retired by DEACTIVATING its revision — the one action
  # that terminates the replicas immediately rather than waiting on an idle scale-down.
  echo "    app exists -> stop-then-start update (ADR-007: never two ledger writers)"
  OLD_REV="$(az containerapp show -n "$APP" -g "$RG" \
    --query properties.latestRevisionName -o tsv 2>/dev/null || echo '')"
  FQDN_NOW="$(az containerapp show -n "$APP" -g "$RG" \
    --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || echo '')"
  if [ -n "$OLD_REV" ]; then
    # Best-effort: single-revision mode may refuse to deactivate the only revision. If it does, the
    # drain loop below still gives the old replica time to exit before the new image is applied.
    az containerapp revision deactivate -n "$APP" -g "$RG" --revision "$OLD_REV" \
      --only-show-errors -o none 2>/dev/null ||
      echo "    (could not deactivate $OLD_REV - falling back to a timed drain)"
  fi
  printf '    draining the old replica '
  for _ in $(seq 1 24); do
    # Gone when the live endpoint stops answering: the writer has released the ledger.
    if [ -z "$FQDN_NOW" ] || ! curl -fsS --max-time 5 "https://$FQDN_NOW/healthz" >/dev/null 2>&1; then
      break
    fi
    printf '.'
    sleep 5
  done
  printf ' stopped\n'
  az containerapp update -n "$APP" -g "$RG" --image "$ACR_LOGIN/$IMAGE_TAG" \
    --min-replicas 1 --max-replicas 1 --only-show-errors -o none
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
      set transport.http_allowed_hosts: ["${FQDN}", "${FQDN}:*"] in the image config and re-deploy.
      (BOTH forms: ":*" only matches a Host header carrying a port; :443 sends none.)
  * Switch identity from the demo static tokens to OIDC (your Entra/Okta tenant):
      docs/features/oidc-identity.md  (adapters.identity: oidc + your tenant).

Tear everything down:
  az group delete -n ${RG} --yes --no-wait
EOF
