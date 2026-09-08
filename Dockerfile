# GateKeeperAI gateway — cloud-neutral container. Azure Container Apps guide:
# docs/deploy/azure-container-apps.md. The image itself runs anywhere.
#
# Posture:
#   * ONE worker / ONE replica: the SQLite ledger has a single writer by construction.
#   * Binds 0.0.0.0 INSIDE the container (the ENV block below is the explicit acknowledgement);
#     TLS terminates at the platform ingress, never in-process.
#   * No secret in the image: GATEKEEPER_HMAC_KEY (+ any upstream {from_env} refs) arrive via the
#     runtime environment; the ledger lives on a mounted volume (/data).
#   * No config baked in beyond the repo defaults: everything a deployment differs on is an
#     environment variable (see config/platform.yaml for the full list), so a hosted gateway is
#     configured at deploy time — never by rebuilding the image.

# --- build stage: build the wheel once, keep build tooling out of the runtime image ---------
FROM python:3.12-slim AS build
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir build && python -m build --wheel

# --- runtime stage ---------------------------------------------------------------------------
FROM python:3.12-slim
WORKDIR /app

# The wheel (migrations included) + the demo extra (the governed third-party demo server) + the
# Postgres driver, so a hosted deployment can point GATEKEEPER_LEDGER_URL at a managed database
# and get a ledger that survives the replica — no rebuild, no second image.
COPY --from=build /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir "$(ls /tmp/*.whl)[postgres]" && \
    pip install --no-cache-dir "mcp-server-time>=2026.6.4" && \
    rm /tmp/*.whl

# Repo defaults. Mount your own dir over /app/config (or set GATEKEEPER_CONFIG_DIR) to change
# the governed servers, identities, or policy.
COPY config ./config
COPY policies ./policies
COPY examples ./examples
COPY deploy/container/entrypoint.sh /entrypoint.sh

# Container runtime configuration — plain environment, overridable at `docker run` / deploy time.
ENV GATEKEEPER_CONFIG_DIR=/app/config \
    GATEKEEPER_TRANSPORT=http \
    GATEKEEPER_HTTP_HOST=0.0.0.0 \
    GATEKEEPER_HTTP_PORT=8765 \
    GATEKEEPER_HTTP_ALLOW_NON_LOOPBACK=1 \
    GATEKEEPER_LEDGER_PATH=/data/audit.db
# Set GATEKEEPER_LEDGER_URL to a Postgres connection string to move the ledger off the container's
# own disk (required for durability and for more than one replica) — see docs/features/durable-ledger.md.

# Non-root; /data is the ledger volume (any persistent mount).
RUN useradd --create-home --uid 10001 gatekeeper && \
    mkdir -p /data && chown -R gatekeeper:gatekeeper /app /data && \
    chmod +x /entrypoint.sh
USER gatekeeper
VOLUME /data
EXPOSE 8765

# Liveness = the same /healthz the platform probes (stdlib only — no curl in the image).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["/entrypoint.sh"]
