#!/bin/sh
# Container entrypoint: migrate the ledger schema, then serve over HTTP.
# Fail-loud: a failed migration stops the container (no half-migrated gateway);
# the missing-HMAC-key guard inside `gatekeeper serve` keeps boot fail-closed.
set -eu

# The ledger sits on a SHARED volume, and the platform may still be retiring a previous replica
# when this one boots. SQLite then reports "database is locked" and the container dies before it
# ever serves (observed on the first live Azure run, 2026-08-24: the new revision crash-looped
# while the OLD one kept serving a stale config). Retry briefly — the deploy script also stops the
# old writer first, so this is the second line of defence, not the primary one. Still FAIL-LOUD:
# after ~60s we refuse to start rather than serve on an unmigrated ledger.
migrate_attempt=0
until alembic -c /app/alembic.ini upgrade head; do
  migrate_attempt=$((migrate_attempt + 1))
  if [ "$migrate_attempt" -ge 12 ]; then
    echo "FATAL: ledger migration still blocked after ${migrate_attempt} attempts (another writer?)" >&2
    exit 1
  fi
  echo "ledger locked - a previous replica may still hold it; retry ${migrate_attempt}/12 in 5s" >&2
  sleep 5
done
gatekeeper seed-demo   # idempotent: seeds the demo sandbox so the out-of-the-box read works
exec gatekeeper serve --transport http
