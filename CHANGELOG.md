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
  and a 3-job CI workflow (quality · security · container) that blocks merge on red.
- `Dockerfile` + `.dockerignore` for reproducible runs (non-root; HMAC key injected at runtime).
