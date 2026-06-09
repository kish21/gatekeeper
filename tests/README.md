# Tests

Four tiers (see `PRODUCT.md` → Tests, written in the /test phase):

- **`unit/`** — isolated logic with ports mocked: hash-chain math, write-detection, policy mapping,
  decision value objects. Fast, no I/O.
- **`integration/`** — real contracts: gateway pipeline against a real example MCP server (and a real
  third-party `mcp-server-time` subprocess), real Cedar engine, real SQLite ledger; end-to-end
  allow/deny/forward + `verify`.
- **`adversarial/`** — the security suite: ledger-tamper attempts (alter/insert/remove → `verify` must
  fail), RBAC bypass attempts, no-ungoverned-path checks, the **classification→RBAC evasion** limitation
  (`test_governance_gaps.py`, pinned + its config mitigation), read access-scoping, and (M2)
  prompt-injection against the risk classifier.
- **`golden/`** — the eval dataset: known `(role, action, upstream, tool) → expected verdict`
  (`rbac_golden.yaml`) run against the **shipped** Cedar policy, so a policy edit that drifts the
  authorization contract fails with the offending case named. The M1 analog of the M2 classifier eval.
