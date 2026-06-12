# Changelog

All notable changes to GateKeeperAI are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **HTTP transport (M3.1):** MCP Streamable HTTP binding of the same governed pipeline —
  shared proxy-surface builder (stdio/HTTP cannot drift), FastAPI+uvicorn single worker
  (ADR-007), per-request `Authorization: Bearer` resolved + recorded in the pipeline
  (ADR-008), fail-closed non-loopback bind guard + DNS-rebinding protection (ADR-009),
  `gatekeeper serve --transport stdio|http`, `/healthz`.
- **OIDC identity adapter (M3.2):** generic PyJWT+JWKS `IdentityResolver` (Entra-first docs):
  signature/issuer/audience/expiry validated, config group→role map, fail-closed on every path;
  `adapters.identity: oidc` is a pure config swap.
- **Container + Azure deploy (M3.3):** multi-stage non-root Dockerfile (migrate→seed→serve),
  container config overlay (/data ledger volume), CI container build+healthz smoke job, and the
  Azure Container Apps deploy guide (1 replica pinned per ADR-007).
- **Observability surface (M3.4):** `GET /metrics` (Prometheus text: calls by verdict, deny
  rate, governance-overhead p95 vs budget), `gatekeeper stats` (ledger-derived health), and a
  fail-safe webhook alert hook (verify-failure + deny-spike) via `GATEKEEPER_ALERT_WEBHOOK`.
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
- **Config-driven any-server + operator CLI (M1.4):** brought a **real, third-party MCP server**
  (`mcp-server-time`, installed via the `demo` extra) under full governance by **editing
  `config/upstreams.yaml` only — zero gateway code**, proving the tool-agnostic promise end-to-end.
  Implemented **`gatekeeper seed-demo`** (non-destructive: seeds the demo sandbox + prints a run
  recipe; shows principal+role but never tokens). Hardened the proxy so one unavailable upstream is
  logged and **skipped** instead of crashing the gateway (no ungoverned bypass).
- **Evaluation (M1 measured):** a reproducible latency eval harness
  `tests/eval/bench_governance_latency.py` that measures the **added gateway governance overhead**
  (classify → Cedar → keyed-HMAC → SQLite append) on the real pipeline with a zero-latency upstream,
  plus a `--diagnose` mode that attributes the overhead to its components and measures the WAL
  mitigation. A config-driven budget knob `config/platform.yaml perf.overhead_p95_ms` (the ADR-001
  baseline) gates regressions. Findings recorded honestly in `PRODUCT.md#Evaluation`: coverage 100% /
  0 bypass, RBAC golden 13/13, **0 operational failures** — and one honest miss, p95 overhead ~2× the
  10 ms budget, root-caused to the durable audit commit with a quantified WAL fix queued for M2.

- **Upstream credentials from `.env` (`{from_env: NAME}`):** an upstream's `env:` value in
  `config/upstreams.yaml` may now reference a secret by **name** (e.g.
  `GITHUB_TOKEN: { from_env: GITHUB_TOKEN }`); the **value** is resolved at launch from `.env` /
  the process environment (`secret_source()`, exported var wins) and injected into the launched
  server — so a credentialed third-party MCP server (GitHub-class) is governed **without any secret
  in YAML**. Fail-closed: a referenced-but-unset secret aborts boot with a clear error; resolved
  values are never logged or persisted. Unit + live-subprocess integration tests; security-reviewed.
- **One-command narrated showcase (`make demo` / `python -m scripts.demo`):** plays the 5-beat
  governance story end-to-end on a terminal — operator read ALLOW → read-only write DENY (Cedar,
  no side effect) → real third-party server governed zero-code → hash-chained ledger `verify` OK →
  a deliberate ledger tamper **caught**. Hermetic (ephemeral HMAC key, throwaway ledger + sandbox
  in a temp dir) and runs the *real* `build_pipeline()` wiring, not a look-alike. Plus
  double-clickable Windows launchers (`RUN-DEMO.bat`, `SHOW-LOGBOOK.bat`, `VERIFY-LOGBOOK.bat`).
- **Non-technical product explainer:** `docs/HOW-IT-WORKS.md` (guard/badge mental model, who-is-the
  agent, config-not-code, deploy story, credentialed-server onboarding) + presentation-ready
  `docs/how-it-works.svg`; README "See it in 30 seconds" section.
- **M3 "Enterprise deployment readiness" cycle (docs):** kicked off from fired, pre-documented
  triggers (anonymized enterprise platform-requirements spec, 2026-06) — `PRODUCT.md` scope + plan
  tables for M3.1–M3.5 (#26) — and the **M3.1 HTTP-transport architecture decisions** (ADR-007
  single-worker serving preserves the ledger's single-writer assumption by construction; ADR-008
  authn enforced + recorded in the pipeline with per-request bearer extraction in transport; ADR-009
  fail-closed loopback-by-default bind) in the `#Architecture` M3.1 addendum (#27). Docs-only; the
  HTTP transport itself lands with the M3.1 build.

### Changed
- CI now installs the `demo` extra in both the test job (so the "govern any server" proof runs for
  real) and the security job (so `mcp-server-time` is also CVE-scanned by pip-audit).
- **Composition root split (`build_pipeline()` / `build_runtime()`):** the config-driven wiring is
  now injectable with an isolated ledger + key, so the showcase and tests drive the *identical*
  governed path `serve` uses. `python-dotenv` added as an explicit dependency.

### Fixed
- **MCP-host robustness (`gatekeeper serve` under Claude Desktop etc.):** three field-found fixes.
  (1) A boot failure is now reported on **stderr** — stdout is the MCP JSON-RPC channel, and the
  previous stdout error corrupted it into opaque `"… is not valid JSON"` host errors. (2) A bare
  `python`/`python3` upstream launcher is pinned to the gateway's **own interpreter**
  (`sys.executable`) so config-declared servers import correctly regardless of the host's PATH.
  (3) An unwritable ledger directory (host launched the gateway with the wrong working directory)
  now surfaces as a clear `ConfigError` with a "set `cwd`" fix hint instead of a raw
  `PermissionError` traceback. Each fix is regression-tested.
- **Upstream session teardown (`McpUpstreamClient.aclose()`):** a pre-existing latent bug where
  shutdown could raise `RuntimeError: Attempted to exit cancel scope in a different task` when an
  upstream session was first opened inside a forward's child task (the MCP server dispatches calls via
  `tg.start_soon`). Each session's anyio lifecycle is now pinned to one dedicated task, so it is opened
  and closed in the same task; `aclose()` is safe to call from any task and never raises on shutdown.
