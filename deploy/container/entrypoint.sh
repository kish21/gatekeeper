#!/bin/sh
# Container entrypoint. The gateway creates or migrates its ledger on boot, refuses to start
# without GATEKEEPER_HMAC_KEY, and refuses to expose the committed demo tokens unless
# GATEKEEPER_ALLOW_DEMO_TOKENS=1 is set explicitly (smoke tests only).
set -eu
gatekeeper seed-demo >/dev/null 2>&1 || true   # sample file for the demo-files server; no secrets
exec gatekeeper serve
