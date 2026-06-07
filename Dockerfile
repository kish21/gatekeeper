# Reproducible runtime for GateKeeperAI. Provided for self-hosting + CI prod-parity; full
# deployment/orchestration is deferred per PRODUCT.md Scope (infra "later"). NO secrets baked in —
# GATEKEEPER_HMAC_KEY is supplied at runtime (`docker run -e GATEKEEPER_HMAC_KEY=...`).
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install the package first (better layer caching), then bring in runtime config.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# Runtime config + policies (deployment data, not secrets).
COPY config ./config
COPY policies ./policies

# Run as non-root.
RUN useradd --create-home --uid 10001 gatekeeper && chown -R gatekeeper /app
USER gatekeeper

ENTRYPOINT ["gatekeeper"]
CMD ["health"]
