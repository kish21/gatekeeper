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

GateKeeperAI is a **stdio MCP server your agent connects to**. The repo ships with a working demo
target (`config/upstreams.yaml` → a local `demo_file_server`), so you can try governance end-to-end
with no extra setup.

```bash
make install        # deps + git hooks
cp .env.example .env # then set two values in .env (see below)
make migrate        # create the tamper-evident audit ledger
make serve          # run the gateway as a stdio MCP server (waits for a client to connect)
```

Set these in `.env` (neither is an external API key):

| Variable | Value | What it's for |
|---|---|---|
| `GATEKEEPER_HMAC_KEY` | output of `openssl rand -hex 32` | local key for the ledger hash-chain (required to boot) |
| `GATEKEEPER_AGENT_TOKEN` | `dev-token-alice-REPLACE-ME` (a dev token from `config/identities.yaml`) | identifies the connecting agent; unknown/unset → refused |

Point your MCP client/agent at the `gatekeeper serve` command (the same way you'd register any stdio
MCP server). It sees the upstream's tools, and **every call is authenticated, decided, and recorded
before being forwarded**. Then, in any shell:

```bash
make tail           # view the audit trail
make verify         # prove the ledger is intact (exit 0 = untampered)
```

> **Not an external service:** `serve` runs entirely local (gateway → a local demo server). No network
> call leaves your machine and no LLM/API key is involved in M1 — that arrives with M2 risk-scoring.
> A one-command demo driver (`seed-demo`) and a fuller usage guide land in **M1.4**.

## Status

Early build — see [`PRODUCT.md`](PRODUCT.md) for the full vision, scope, plan, and architecture
(ADRs included), and [`STRUCTURE.md`](STRUCTURE.md) for the codebase map.

| Milestone | Scope | State |
|---|---|---|
| **M1** | governed verifiable proxy (identity · RBAC · hash-chain ledger · `verify` · config-driven) | building — **M1.1 ✅** transparent proxy + audit feed · **M1.2** RBAC next · M1.3/M1.4 pending |
| **M2** | LLM risk-scoring + human write-approval | planned |

## License

Apache-2.0. See [`LICENSE`](LICENSE). Security policy: [`SECURITY.md`](SECURITY.md).
