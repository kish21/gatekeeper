# GateKeeperAI gateway — cloud-neutral container (M3.3). Azure-first proof lives in
# docs/deploy/azure-container-apps.md; the image itself runs anywhere.
#
# Posture (matches the ADRs):
#   * ONE worker / ONE replica (ADR-007: ledger single-writer by construction).
#   * Binds 0.0.0.0 INSIDE the container only via the explicit ADR-009 ack in
#     deploy/container/platform.yaml — TLS terminates at the platform ingress, never in-process.
#   * No secret in the image: GATEKEEPER_HMAC_KEY (+ any upstream {from_env} refs) arrive via
#     the runtime environment; the ledger lives on a mounted volume (/data).

# --- build stage: build the wheel once, keep build tooling out of the runtime image ---------
FROM python:3.12-slim AS build
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir build && python -m build --wheel

# --- runtime stage ---------------------------------------------------------------------------
FROM python:3.12-slim
WORKDIR /app

# The wheel + the demo extra (the governed third-party demo server, same as CI exercises).
COPY --from=build /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && \
    pip install --no-cache-dir "mcp-server-time>=2026.6.4" && \
    rm /tmp/*.whl

# Migrations run from the source tree exactly like CI does (alembic.ini -> src/...).
COPY alembic.ini ./alembic.ini
COPY src/gatekeeper/db ./src/gatekeeper/db
# Default deployment config: the repo config overlaid with the container platform.yaml
# (http transport, 0.0.0.0 + ADR-009 ack, ledger on /data). Mount your own dir over /app/config
# (or set GATEKEEPER_CONFIG_DIR) for a real deployment.
COPY config ./config
COPY policies ./policies
COPY examples ./examples
COPY deploy/container/platform.yaml ./config/platform.yaml
COPY deploy/container/entrypoint.sh /entrypoint.sh

# Non-root; /data is the ledger volume (Azure Files / any persistent mount).
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
