# GateKeeperAI

**A tool-agnostic, *verifiable* governance gateway for the Model Context Protocol (MCP).**

GateKeeperAI sits between an AI agent and the MCP servers it calls. Every tool call is
**authenticated**, **RBAC-checked**, **approved-on-write**, and recorded in a **tamper-evident,
hash-chained audit ledger** — for *any* MCP server you plug in by config.

> Most MCP gateways treat governance as routing ("forward the call, check a token, log it").
> GateKeeperAI's wedge is **verifiable governance**: *provable policy* (Cedar, analyzable) +
> *provable audit* (keyed-HMAC hash-chain). **Don't trust the gateway — verify it.**

---

## Why

The MCP standard says nothing about authn, authz, write-safety, or audit. As agents move from demos to
production — performing real **writes** on real systems — that gap is the blocker. GateKeeperAI closes it
with one config-driven control plane, so a platform/security engineer can adopt agents without losing
control or failing an audit.

## How it works

```
 Agent ──MCP──▶ GateKeeperAI ──MCP──▶ any upstream MCP server
                    │
   identity ▶ policy(Cedar) ▶ [M2: risk(LLM) ▶ human approval] ▶ audit-write ▶ forward
                                                                  (fail-closed, audit-before-act)
```

- **Authenticated** — every call resolves to a principal + role (`IdentityResolver`).
- **Authorized** — allow/deny per role × tool as **policy-as-code** (Cedar `.cedar` files).
- **Approved-on-write (M2)** — an LLM risk-scores calls; risky/write calls wait for a human.
- **Provably logged** — append-only, keyed-HMAC hash-chained ledger; `gatekeeper verify` proves
  no record was altered, inserted, or removed.
- **Tool-agnostic** — govern any MCP server by editing `config/upstreams.yaml`. Zero code per server.

## Quickstart

```bash
make install        # deps + git hooks
cp .env.example .env && $EDITOR .env   # set GATEKEEPER_HMAC_KEY
make seed           # example upstream + identities + policy
make serve          # run the governed gateway
make verify         # prove the audit ledger is intact
```

## Status

Early build — see [`PRODUCT.md`](PRODUCT.md) for the full vision, scope, plan, and architecture
(ADRs included), and [`STRUCTURE.md`](STRUCTURE.md) for the codebase map.

| Milestone | Scope | State |
|---|---|---|
| **M1** | governed verifiable proxy (identity · RBAC · hash-chain ledger · `verify` · config-driven) | building |
| **M2** | LLM risk-scoring + human write-approval | planned |

## License

Apache-2.0. See [`LICENSE`](LICENSE). Security policy: [`SECURITY.md`](SECURITY.md).
