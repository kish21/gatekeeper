# Security Policy

GateKeeperAI is a security product, so we hold our own code to a high bar.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's **"Report a vulnerability"** (Security tab → Advisories) for private disclosure,
or email the maintainer. We aim to acknowledge within 72 hours and to agree a disclosure
timeline with you.

## Scope

In scope: the gateway decision path (identity, policy, approval), the audit-ledger integrity
mechanism (hash-chain / HMAC), config loading, and the adapter interfaces.

## Design stance (defense baseline)

- **Fail-closed**: any error in identity, policy, or ledger-write results in *deny*, never allow.
- **Audit-before-act**: a call is recorded in the tamper-evident ledger *before* it is forwarded.
- **No secret in source**: secrets live only in `.env`; `gitleaks` runs in pre-commit and CI.
- **Known, documented residual risks** are tracked as ADRs in `PRODUCT.md` (e.g. ADR-006:
  bearer-token replay → sender-constrained tokens, deferred with a trigger).
