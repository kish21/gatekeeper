# Changelog

All notable changes to GateKeeperAI are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added — the desk, and the whole company behind the guard
- **`gatekeeper ui`**, a web page for the people who are not engineers: writes waiting for a
  decision as cards with Approve/Deny and a reason; the activity as a filterable list with each
  call's full story; a one-click integrity check with counts; the governed servers and their
  read/write tools. Runs next to a stdio gateway (shared ledger) and is mounted at `/ui` on the
  HTTP transport. Open on loopback; beyond it only behind `GATEKEEPER_UI_TOKEN`.
- **Five company systems governed out of the box**: demo twins of SharePoint, Jira, GitHub, a
  database and a mailbox, with the same tool names as the real servers and in-memory data, so
  the full flow shows without a tenant or token. The real GitHub server is a commented config
  block away.
- **`scripts/demo_company.py`** plus `docs/DEMO-COMPANY.md`: a twelve-minute presenter's script
  with a real transcript and screenshots. `--auto` rehearses it by deciding through the UI API.
- A call whose caller disconnected while waiting now gets a chained `deny` entry, so nothing is
  left looking pending forever.

### Added — a human approves writes
- **The approval gate.** A write the policy allows is held: recorded as `pending`, queued, and
  the gateway waits for `gatekeeper approve <id>` or `gatekeeper deny <id> --reason ...` from
  another process. Approved -> a chained `allow` entry naming the approver, then the forward.
  Denied, timed out (default 90 s), or cancelled because the caller went away -> a chained
  `deny` entry and no forward. Reads are never held; `exempt_roles` (admin) pass. Configured in
  `config/product.yaml` `approval` or `GATEKEEPER_APPROVAL_WRITES` / `_TIMEOUT_S`. The queue
  lives in the ledger's database (migration 0002); the arguments preview a person decides on is
  blanked once decided, and the ledger itself never stores raw arguments.
- `gatekeeper pending`, `approve`, `deny`; `show` now displays a call's whole lifecycle and
  accepts an id prefix; `tail --with-id` prints copyable ids; `stats` counts held calls.
- `scripts/agent.py`, a stand-in assistant that makes one governed call over stdio, so the
  approval flow can be practised without an MCP host.
- `docs/WALKTHROUGH.md`: one afternoon with GateKeeper, pasted from a real run.
- Governed servers launch from the project root by default, so `python -m examples...`
  launchers work when an MCP host starts the gateway from elsewhere; `doctor` resolves them the
  same way and points the host at this environment's `gatekeeper` binary.

### Fixed
- The ledger store held the SQLite write lock between operations (a refresh after each append
  and every read opened a transaction that was never ended), which blocked any second process.

### Changed — make it easy to run, and honest about what is hosted
- **Two-command first run.** `gatekeeper init` generates the HMAC key and agent token into `.env`,
  creates the ledger (migrations run on boot now; `make migrate` is no longer a required step), and
  seeds the demo files. `gatekeeper doctor` checks key, ledger, policy, token and every server's
  launcher, then prints the `mcpServers` block to paste into an MCP host, with absolute paths.
- **Paths resolve against the project root**, not the working directory, so a host launching the
  gateway from anywhere finds `.env`, the ledger and the policies via `GATEKEEPER_CONFIG_DIR`.
- **Every runtime knob is an environment variable** (`GATEKEEPER_TRANSPORT`, `_HTTP_*`,
  `_LEDGER_PATH`, `_IDENTITY`, `_OIDC_*`, `_IDENTITIES`). The container has no baked config overlay
  any more; `deploy/container/platform.yaml` is gone.
- **Azure deploy needs no second build.** The platform's `CONTAINER_APP_HOSTNAME` is trusted
  automatically; each configured host is accepted with and without a port. The script issues fresh
  per-deployment tokens as a platform secret and prints the probe command; OIDC is a `--set-env-vars`
  away. Storage defaults to the container disk with the SMB finding stated up front
  (`GK_LEDGER_STORAGE=files` keeps the old path).
- **Docs restructured for readers, not the build process.** README leads with the three questions
  and a real demo transcript; new `docs/getting-started.md`, `docs/glossary.md`, a single deploy
  guide. `PRODUCT.md`, the first-run explainer and its runbook moved to `docs/internal/`. Windows
  launchers moved to `scripts/windows/`. Unread config knobs and the empty next-milestone packages
  were removed.

### Fixed
- **Ledger:** a failed append is rolled back, so one disk-full or lock timeout denies that call
  instead of every call until restart. The engine now uses WAL, a busy timeout, and
  `BEGIN IMMEDIATE`, so two processes can never both read the same chain head and fork the chain
  (test added). `verify` reports the head hash and accepts `--expect-head` to detect records removed
  from the end of the chain.
- **Upstream launch environment:** governed servers receive a minimal spawn environment plus their
  declared variables, instead of the gateway's entire environment (API keys and cloud credentials
  no longer leak to every server). A session that fails mid-call is dropped and relaunched on the
  next call instead of timing out forever. Error text written to the ledger is capped.
- **Public bind with the repository's demo tokens is refused** (`GATEKEEPER_ALLOW_DEMO_TOKENS=1`
  opts a smoke test in).
- **OIDC:** the issuer is compared verbatim (trailing-slash IdPs such as Auth0/Keycloak work);
  default clock-skew leeway is 30 s instead of 0.
- **Dependency pin:** `mcp>=1.27.2,<2`. The 2.x SDK renamed the client API and broke a fresh
  install.

### Fixed
- **First live Azure run (2026-08-24) — five defects in the deploy path**, none reachable by review:
  - `az acr build` log streaming crashed the CLI on a Windows cp1252 console
    (`UnicodeEncodeError` in colorama) while the server-side build kept running → build is now
    queued with `--no-logs` and **polled to completion**, so a failed build still stops the deploy.
  - `az storage share-rm create` was missing `-g` → `argument 'resource_group' is not defined`.
  - Deploys pushed `:latest` and updated to `:latest`; Container Apps compares image references,
    saw no change, and **silently kept the old revision** → each build now gets a unique timestamp
    tag (`:latest` still pushed as the human pointer).
  - The documented `http_allowed_hosts: ["<fqdn>:*"]` form **can never match a real request**: the
    SDK's `:*` pattern requires a port in the Host header, and `:443` traffic sends none. Every
    `/mcp` call 421'd. Guide, container config, script hint and runbook now say to list the FQDN
    **bare and with `:*`**.
  - Rolling updates put **two writers on the single-writer ledger** (ADR-007): the new revision died
    in `alembic upgrade head` with `database is locked` while the old one served a stale config.
    The deploy is now **stop-then-start** (old revision deactivated + drained first), and the
    container entrypoint retries a locked migration for ~60 s before failing loud.

### Known issues
- **The ledger does NOT persist on Azure Files (SMB)** — measured 2026-08-24 on a live deployment:
  `audit.db` stayed 0 bytes while governed calls were served, a second process reported
  `Ledger table not found`, and a restart lost every record. SQLite needs POSIX locking + honest
  `fsync`, which SMB does not provide. M3.3's *"ledger on persistent storage; `verify` clean"*
  clause is **failed, not pending**; the governance path itself measured clean. Candidate fixes
  (Azure Files NFS · managed disk · Postgres ledger) are recorded in
  `docs/deploy/azure-container-apps.md`.

### Added
- **Hosted-deploy acceptance kit:** `scripts/probe_hosted.py` (drives a real hosted gateway from
  outside the cloud: governed list, operator ALLOW, RBAC DENY, identity DENY, `/metrics`; keeps
  `allowed`/`denied`/`error` **distinct** so a transport failure can never score as a passing deny)
  and `docs/runbooks/verify-hosted-deploy.md` (nine checks, plain-language, with the first live
  run's results recorded).
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
- **M3 evaluation harness:** `tests/eval/bench_transport_overhead.py` — drives the real
  `serve --transport` binary over stdio + HTTP and measures the added HTTP overhead, gated by
  `perf.http_transport_overhead_p95_ms` (config). Test-harness + config only; no runtime change.
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
