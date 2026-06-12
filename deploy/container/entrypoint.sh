#!/bin/sh
# Container entrypoint: migrate the ledger schema, then serve over HTTP.
# Fail-loud: a failed migration stops the container (no half-migrated gateway);
# the missing-HMAC-key guard inside `gatekeeper serve` keeps boot fail-closed.
set -eu

alembic -c /app/alembic.ini upgrade head
gatekeeper seed-demo   # idempotent: seeds the demo sandbox so the out-of-the-box read works
exec gatekeeper serve --transport http
