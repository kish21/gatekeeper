# Tests

Three tiers (see `PRODUCT.md` → Tests, written in the /test phase):

- **`unit/`** — isolated logic with ports mocked: hash-chain math, write-detection, policy mapping,
  decision value objects. Fast, no I/O.
- **`integration/`** — real contracts: gateway pipeline against a real example MCP server, real Cedar
  engine, real SQLite ledger; end-to-end allow/deny/forward + `verify`.
- **`adversarial/`** — the security suite: ledger-tamper attempts (alter/insert/remove → `verify` must
  fail), RBAC bypass attempts, no-ungoverned-path checks, and (M2) prompt-injection against the
  risk classifier.
