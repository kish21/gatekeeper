# Changelog

All notable changes to GateKeeperAI are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added
- Product definition (`PRODUCT.md`): vision, scope, plan, architecture (ADR-001…006).
- Project structure + root scaffolding: src-layout package skeleton, layered ports-&-adapters
  folders, config engine (`config/*.yaml` + typed loader), secret-scan, pre-commit, Makefile, `STRUCTURE.md`.
- **Foundation (walking skeleton):** `gatekeeper health` command (config table + JSON log); typed
  config loader with a **fail-loud / fail-closed startup guard** (refuses to boot without a valid
  ledger HMAC key); structured JSON logging + tracing/error-reporter port; Alembic migration env
  (DB URL derived from config); 9 unit tests (config-flow + guard + Windows-console regression).
- **Auto-layer:** ruff (lint+format) + mypy, pip-audit dep-vuln scan, Dependabot (grouped),
  and a 2-job CI workflow (quality · security) that blocks merge on red.
- **Contracts:** typed domain models (`Principal`, `ToolCall`, `ToolResult`, `Decision`,
  `RiskAssessment`, `LedgerEntry`, `VerifyResult`); five typed port interfaces (Identity, Policy,
  Ledger, Upstream, LLM); and the first DB migration `0001_create_ledger` (append-only, hash-chained
  audit table). Schema↔code proven via `alembic check` (no drift) + an integration test.
- **Tamper-evident audit ledger (first feature):** keyed-HMAC hash-chained `SqliteLedgerStore`
  (`append`/`read`/`get`/`verify`) and `gatekeeper verify` / `tail` CLI. `verify` detects any edit,
  deletion, reorder, insert, or wrong key and pinpoints the broken entry; it also emits the head hash
  for out-of-band pinning. Append-only + fail-closed on the HMAC key; raw args/output never stored.
- **Transparent governed MCP proxy (M1.1):** `gatekeeper serve` — a stdio MCP proxy that re-exposes an
  upstream's tools by name and runs every call through the pipeline (identity → classify →
  audit-before-act → forward → audit-outcome). No ungoverned bypass; fail-closed identity; PII-safe.
- **Identity + RBAC policy-as-code — Cedar (M1.2):** `CedarPolicyEngine` PDP at pipeline step 3
  evaluates (role × action × tool) against version-controlled `policies/gatekeeper.cedar` →
  allow/deny + reason; both verdicts recorded; default-deny / fail-closed eval + fail-loud policy load.
- **Tamper-evidence gate + `show` (M1.3):** confirmed `gatekeeper verify` pinpoints any forgery on a
  ledger now carrying RBAC allow/deny verdicts, and added **`gatekeeper show <call_id>`** to inspect
  the recorded governance decision for one call (exit 0 found / 1 not-found / 2 misconfig; no
  token/key leak; PII-safe).
