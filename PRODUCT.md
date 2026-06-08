# PRODUCT.md — GateKeeperAI

> The shared spine of this product. Each playbook phase fills its own section.
> **AI product? YES** (uses an LLM to risk-score/classify tool calls → the AI-security layer applies downstream.)

> ### ⏯ RESUME MARKER — next session
> **Done:** Vision ✅ · Scope ✅ · Plan ✅ · Architecture ✅ · Structure ✅ · Foundation ✅ · Contracts ✅
> (typed models + 5 port interfaces + migration `0001_create_ledger`; schema==code via `alembic check`).
> **Next phase:** **`/build` — M1.1** (the first feature): a transparent pass-through MCP proxy that
> forwards a call to a real upstream and appends a `LedgerEntry` (the hash-chain `append`/`verify` in
> `adapters/ledger/`). Build ONE feature, security in the definition-of-done.
> **Dev setup:** `.venv` has full deps (`pip install -e ".[ai]"`). Run: `GATEKEEPER_HMAC_KEY=$(openssl rand -hex 32) gatekeeper health`.
> **How to resume:** fresh session → run **`/playbook`** or **`/build`** directly.

---

## Vision

**One-sentence vision**
> A world where any organization can let AI agents act on real systems with total confidence — because **every** tool call an agent makes is authenticated, authorized, approved-on-write, and recorded in a tamper-evident ledger, for **any** MCP server, driven entirely by config.

**Who it's for (named target user)**
The **platform / security engineer** at a company adopting AI agents — the person on the hook for making agent→tool access safe, auditable, and compliant. They don't want to hand-roll auth/RBAC/audit into every MCP server; they want one governed control plane.

**The problem (and why NOW)**
The Model Context Protocol standardizes how agents discover and call tools, but the protocol itself does **not** handle authentication, authorization, audit trails, or write-safety. As agents move from demos to production in 2026, that gap is the blocker:
- Agents now perform **write actions** on real systems (DBs, repos, infra) — a wrong/destructive/injected call has real blast radius.
- **Regulation is landing now:** the majority of EU AI Act high-risk rules come into force **2 Aug 2026**, demanding structured audit trails and human oversight of automated actions.
- Enterprises need **provable** evidence (SOC2/HIPAA/GDPR) that every agent action was authorized and recorded — plain logs aren't trusted because they can be altered.

**Value proposition (how this is better/different)**
Existing gateways (managed: MintMCP, MCP Manager, TrueFoundry; OSS: MCPX, ContextForge, Bifrost, mcp-audit) treat governance as a **routing/proxy** concern — forward the call, check a token, log it. GateKeeperAI's wedge is **verifiable governance**:
1. **Tamper-evident audit ledger** — hash-chained, append-only; you can *prove* no record was altered or removed, not just trust that it was logged.
2. **Policy-as-code** — governance rules are a declarative, version-controlled contract, so you govern **any** MCP server purely by config (zero code per server).
3. **LLM-assisted write-safety** — deterministic policy (authN, RBAC, allow/deny) first, then an **LLM risk classifier** flags destructive/injected calls and routes them to human approval.
Tagline: *"Don't trust the gateway — verify it."*

**2026 market / competitor read (verified, real comparables)**
- **Managed/commercial:** [MintMCP](https://mcpmanager.ai/blog/best-mcp-gateway-enterprises/), [MCP Manager](https://mcpmanager.ai/blog/best-mcp-gateway-security-teams/), [TrueFoundry](https://www.truefoundry.com/blog/enterprise-mcp-governance-control-audit-secure-mcp-server-access) — auth + RBAC + audit, SOC2, closed-source.
- **Open-source:** [MCPX / Lunar.dev](https://www.lunar.dev/post/the-best-open-source-mcp-gateways-in-2026), [ContextForge / IBM](https://bytebridge.medium.com/mcp-gateways-in-2026-top-10-tools-for-ai-agents-and-workflows-d98f54c3577a) (policy engine + HITL), [Bifrost](https://composio.dev/content/best-mcp-gateway-for-developers), [`mcp-audit`](https://github.com/P4ST4S/mcp-audit) (signed audit Go proxy).
- **Honest read:** the *feature list* (auth+RBAC+approval+audit) is commoditized. The **defensible gap** is making the audit trail a **first-class, verifiable artifact** + clean **policy-as-code** for arbitrary MCP servers. That is GateKeeperAI's reason to exist and its portfolio story (security + systems-design depth).
- **Standards to align with:** MCP OAuth 2.1 resource-server authorization spec (2025-11-25); structured JSON audit records for SIEM ingestion.

**North-star success metric** *(locked ✅)*
**Verifiable governance coverage = 100% of agent tool calls authenticated + policy-decided + written to the hash-chained ledger, with 0 ungoverned bypass paths** (plain: *every single tool call is accounted for and provable — none slip past*).
- Portfolio secondary: **time-to-govern a new MCP server = config-only, < a few minutes, zero code.**

**Job-to-be-done** *(locked ✅)*
> *When* I let AI agents call real tools / MCP servers on our behalf, *I want* every call to be authenticated, authorized, approved-on-write, and provably recorded, *so I can* adopt agents in production without losing control or failing an audit.

**Riskiest assumption** *(locked ✅)*
That platform/security engineers will accept a **mandatory proxy in the hot path** of every agent tool call — i.e. the governance value (and verifiable audit) outweighs the added latency and the new single-point-of-failure — **and** that LLM risk-scoring adds enough value over pure deterministic rules to justify its cost/latency.

**Business model**
**Open-core / commercial-ready:** Apache/MIT OSS core (the public portfolio artifact), architected so a paid tier (SSO, multi-tenant, hosted control plane) is a natural extension — signals product thinking without building the paid tier now.

---

## Scope

**THE core feature (ship-only-one)**
A **governed, verifiable MCP proxy**: every tool call to any config-registered MCP server is intercepted →
identity-checked → RBAC-decided (allow/deny via policy-as-code) → forwarded or blocked → appended to a
**tamper-evident, hash-chained audit ledger** that can be **independently verified**. Tool-agnostic by config.
> Alone this delivers the core value: *authenticated + authorized + tool-agnostic + provably logged.* It is also the wedge ("verifiable governance"). Everything else layers on this decision point.

**In-scope — Milestone 1 (the core, built first)** — each tied to a customer outcome:
| In-scope item | Customer outcome (security engineer can…) | Serves |
|---|---|---|
| Transparent MCP proxy (stdio + HTTP transport) | …drop the gateway in front of an agent with no code change to agent or server | tool-agnostic |
| Config-driven upstream registration | …govern **any** MCP server by editing config — zero code per server | tool-agnostic / north-star secondary |
| Identity (token → principal → role) | …know *who* every call is on behalf of | authenticated |
| RBAC policy-as-code (allow/deny per role × tool) | …declare, version-control, and enforce who may call what | authorized |
| Tamper-evident hash-chained ledger | …record every call+decision in an append-only chain | provably logged (wedge) |
| `verify` integrity command | …**prove** no audit record was altered or removed | provably logged (wedge) |
| Minimal operator surface (CLI: tail log, verify, show decision) | …see live decisions and read/verify the audit trail | usable core |

**In-scope — Milestone 2 (committed; built right after the core is verified)**
| Item | Customer outcome | Trigger to start |
|---|---|---|
| LLM risk-scoring of tool calls | …auto-flag destructive / prompt-injected calls beyond static rules | M1 core proxy + ledger demoed & integrity-verified |
| Human-in-the-loop **write-approval gate** (approve/deny queue) | …require a human OK before risky/write calls execute | same |
> This is the standout AI differentiator and is **part of the locked product scope** — not deferred indefinitely. Its trigger is internal (core done), not an external signal.

**Deferred (real external trigger required to pull in)**
| Deferred item | Trigger that would justify it |
|---|---|
| Web dashboard / approval UI (vs CLI) | A user/reviewer can't operate via CLI, or the approval flow needs non-engineers |
| SSO / OIDC identity integration | A real deployment needs enterprise identity (replaces token→role stub) |
| **Sender-constrained tokens (DPoP / mTLS)** behind `IdentityResolver` — defeats stolen-bearer-token replay (see ADR-006) | The gateway is exposed **beyond a trusted local/loopback boundary** (network-reachable), **or** real OIDC identity lands — i.e. when bearer-token replay becomes a realistic threat |
| Multi-tenant / org isolation | More than one team/tenant shares one gateway instance |
| Rate limiting / cost budgets | An agent-runaway or cost-overrun incident is observed |
| Policy editor UI / policy linting | Policy files grow large enough to be error-prone by hand |
| Additional transports / protocol versions | A target server uses a transport beyond stdio+HTTP |

**Non-goals (deliberately NEVER build)**
- A **general-purpose API gateway** — we govern MCP tool calls, not arbitrary HTTP traffic.
- **Building MCP servers / tools themselves** — we govern servers others run; we don't author them.
- **Replacing the identity provider** — we *integrate* identity, we are not the IdP / user store.
- **A secrets vault / data-plane crypto store** — we reference secrets via config/env, not store them.
- **An agent framework / orchestrator** — we sit *between* agents and tools; we don't build the agent.

## Plan

**Sequencing principle:** core-first, thin vertical slices. M1.1 is the smallest end-to-end thing that runs
(agent → gateway → real upstream → response, recorded). Each later slice adds one capability to that live path.
Timeline is **relative** (one slice ≈ one build session); calendar dates are not committed for a portfolio build.

### Milestone 1 — Governed verifiable proxy (THE core)
| # | Slice | Testable exit criterion ("done when…") |
|---|---|---|
| **M1.1** | Transparent pass-through proxy + append-only ledger | An agent calls a tool **through** the gateway against a real config-registered MCP server, gets the correct result, and the call+response-summary appears as an entry in an append-only ledger. Proxy adds no behavioral change vs calling the server directly. |
| **M1.2** | Identity + RBAC policy-as-code | A call carrying a token resolves to a principal+role; a role **lacking** permission for a tool is **blocked with a reason** (fail-closed), an allowed one passes — and **both** decisions are recorded. Policy lives in a version-controlled config file, not code. |
| **M1.3** | Tamper-evidence + `verify` | Ledger entries are **hash-chained**. A `verify` command **passes** on an intact ledger and **fails, pinpointing the entry**, when any record is altered, inserted, or removed. |
| **M1.4** | Config-driven any-server + operator CLI | A **second, different** MCP server is brought under governance by **editing config only (zero code)**; operator CLI can `tail` the log, run `verify`, and show the decision for a call. |
| **M1 exit (gate)** | — | All of the above pass on the live path; `/security-review` of the decision/ledger path is clean; a fresh user can govern an arbitrary MCP server from config + docs alone. |

### Milestone 2 — AI write-safety (committed; starts when M1 exit is verified)
| # | Slice | Testable exit criterion |
|---|---|---|
| **M2.1** | Write/risk classification | Each call is classified read vs write and assigned a risk score (static rules + an **LLM classifier behind a provider interface**). A destructive call scores high, a read scores low; the classification + rationale are recorded in the ledger. |
| **M2.2** | Human-in-the-loop write-approval gate | A high-risk/write call is **held pending** human approve/deny; approved → forwarded, denied → blocked; the approver identity + decision are recorded in the **verifiable** ledger. Fail-closed: no approval ⇒ no execution. |
| **M2 exit (gate)** | — | A write call demonstrably blocks until a human approves; classifier evaluated for accuracy + prompt-injection resistance; full chain still `verify`-clean. |

### Out-of-scope (referenced, NOT scheduled — pull in only on trigger)
Web dashboard, SSO/OIDC, multi-tenant, rate-limit/budgets, policy-editor UI, extra transports — triggers in `#Scope`.

### Concern-area coverage checklist (production-readiness)
| Area | When | Note / trigger |
|---|---|---|
| **Security** | **NOW** | This *is* a security product: authN, RBAC, fail-closed, tamper-evident audit are core. `/security-review` on the decision+ledger path is an M1 gate. |
| **AI-specific** | **NEXT (M2)** | LLM risk classifier behind a provider adapter; prompt-injection resistance + classifier eval. Trigger: M2 start. |
| **Observability** | **NOW** | Structured logging + the audit ledger IS the observability spine; every call traced end-to-end. |
| **Developer-experience** | **NOW** | Config-driven, CLI, drop-in proxy — directly serves the north-star secondary (time-to-govern a new server). |
| **Testing** | **NOW** | Unit (policy engine, hash-chain), integration (real upstream MCP server), adversarial (tamper attempts, RBAC bypass, no-bypass paths). |
| **Infra / deploy** | **LATER** | Local + CI now; containerize/multi-tenant deferred. Trigger: a real hosted deployment. |
| **Documentation** | **NOW** | Docs-driven & portfolio-first: README, architecture doc, policy reference kept in sync each phase. |
| **Product** | **NOW** | Vision/scope locked; `/drift-check` before each milestone. |

## Architecture

**System kind:** an **agentic infrastructure proxy + CLI** (not a web app). It is a man-in-the-middle
between an AI agent and the MCP servers it calls — a Policy Enforcement Point with an attached audit ledger.

### Stack core (best-2026 OSS, each with a one-line why)
| Concern | Choice | Why |
|---|---|---|
| Language / runtime | **Python 3.12, fully async** | Mature official MCP SDK + first-class AI layer (M2) + reuses the FastAPI toolkit. Latency (the Python weak spot) is mitigated with async I/O and a documented budget; the wedge is correctness/security, not throughput. |
| MCP protocol | **official MCP Python SDK** (`mcp`) | Gateway is an MCP **server** to the agent and an MCP **client** to each upstream. Speaks stdio + streamable HTTP. Don't reinvent JSON-RPC framing. |
| Policy engine | **Cedar** (`.cedar` policy-as-code) | Deterministic + formally **analyzable** → "provable policy" matches the verifiable-governance wedge. Rejected: OPA/Rego (sidecar, error-prone), Casbin (no formal analysis). |
| Audit ledger | **SQLite**, **keyed HMAC-SHA256 hash-chain**, via SQLAlchemy + **Alembic migrations** | Single-file, queryable by CLI, append-only chain. HMAC key in `.env` ⇒ tampering can't be re-forged without the key. Rejected: bare SHA-256 (forgeable), Postgres-now (infra deferred), JSONL (not queryable). |
| HTTP transport + M2 approval API | **FastAPI + Uvicorn** (async) | Async serves the stdio+HTTP MCP transport and the M2 approve/deny endpoints without blocking the event loop. |
| Config | **pydantic-settings** (`.env`) + **YAML** (upstream registry, identity map) + `.cedar` (policy) | Everything config-driven, validated at load, zero hardcoding. Secrets only in `.env`. |
| Operator CLI | **Typer + Rich** | Type-hint CLI (`tail`, `verify`, `show`, `serve`) matching the toolkit idiom. |
| LLM (M2) | **`LLMProvider` adapter**, default **Claude Haiku** | Cheap/fast risk classification behind a config-selected interface; pluggable (OpenAI/local) + deterministic stub for tests. Never imported in business logic. |

### Architecture = ports & adapters (hexagonal), layered, decoupled
```
 Agent ──MCP──▶ [Transport]  speaks MCP (stdio/HTTP), no business logic
                    │
                    ▼
              [Gateway pipeline]  ← the PEP; chain-of-responsibility:
   identity ▶ policy(PDP) ▶ (M2: risk ▶ approval) ▶ audit-write ▶ forward
        │         │                 │       │            │          │
        ▼         ▼                 ▼       ▼            ▼          ▼
  IdentityResolver Cedar       RiskClassifier ApprovalGate LedgerStore UpstreamClient
   (token→role)  PolicyEngine  (LLMProvider)  (HITL queue) (SQLite+HMAC) (MCP client → real server)
```
Dependencies point **inward**; every box above the bottom row is an **interface** with a swappable adapter.

### Key ADRs
- **ADR-001 — Python async over Go.** Decision: build in async Python. Why: AI-native M2, mature MCP SDK, toolkit reuse, fastest deep build. Rejected: Go (lower latency, but the wedge isn't throughput and the AI layer is more plumbing). Mitigation: async everywhere + published latency budget.
- **ADR-002 — Cedar for policy-as-code.** Decision: Cedar `.cedar` files as the PDP. Why: deterministic + analyzable = provable policy, the thematic core of "verifiable governance". Rejected: OPA/Rego (error-prone sidecar), Casbin (no formal analysis).
- **ADR-003 — Audit-before-act, fail-closed, keyed hash-chain.** Decision: write the HMAC-chained ledger entry **before** forwarding; deny on any identity/policy/ledger error. Why: this is what makes the north-star ("no call slips past, all provable") literally true. Rejected: log-after / best-effort logging (creates ungoverned bypass windows).
- **ADR-004 — Ports & adapters for every external + per-adapter resilience.** No vendor SDK in business logic; each external is an interface (below).
- **ADR-005 (AI) — Risk-scoring only on writes; classifier fails closed.** Decision: run the LLM only on write/risky calls; on classifier timeout/error → route to **human approval** (never auto-allow). Reads stay fast and free. Prompt is versioned + evaluated (below).
- **ADR-006 — Sender-constrained tokens (DPoP / mTLS): documented now, deferred.** *Threat:* M1 identity uses **bearer tokens** (static token→role map). A bearer token proves *knowledge*, not *possession* — if one leaks (logs, exfiltration, MITM, a compromised agent), an attacker can **replay** it and impersonate the principal; every downstream RBAC decision and audit entry then trusts a stolen identity, silently. *Fix:* **sender-constrained / proof-of-possession tokens** — **DPoP** (RFC 9449: a per-request JWT signed by a key the client holds, binding the token to that key) or **mTLS-bound tokens** (RFC 8705: token bound to the client's TLS cert). The token becomes useless without the private key, so theft alone grants nothing. *Decision:* the `IdentityResolver` adapter seam already isolates identity verification, so a sender-constraint check is a **drop-in later** with no pipeline change — **document and defer, do not implement now** (M1 runs trust-local/loopback). See Scope → Deferred for the trigger.

### Externals → adapter + resilience strategy
| External | Adapter interface | Resilience (timeout · retry · fallback) |
|---|---|---|
| Upstream MCP server | `UpstreamClient` | per-upstream timeout; retry **transient/idempotent** only; circuit-breaker; on failure → **deny + log** (never hang the agent). |
| LLM (M2 risk) | `LLMProvider` | timeout + transient retry; on failure → **fail-closed to "requires approval"**; cheap model + cache identical classifications. |
| Ledger store | `LedgerStore` | write **must** succeed before forward; on failure → **deny** (no un-audited calls). |
| Identity | `IdentityResolver` | static token→role map now (stub), OIDC later via same interface; unknown/invalid token → **deny**. |

### Patterns applied / anti-patterns avoided
- **Applied:** Proxy/MITM · PEP↔PDP separation · Chain-of-responsibility pipeline · Ports & adapters.
- **Avoided:** vendor-SDK-in-logic (→ adapters) · god-object gateway (→ staged pipeline) · hardcoding/dead-config (→ validated pydantic config) · blocking the event loop (→ async I/O) · **fail-open** (→ fail-closed everywhere) · distributed-monolith (→ one deployable, clean seams).

### Perf / cost budget
- **M1 (deterministic):** added gateway overhead target **p95 < ~10 ms** over a direct call (Cedar eval + HMAC + SQLite append). Reads never touch an LLM.
- **M2 (AI):** LLM risk-scoring **only on writes**; target **p95 < ~1 s** for a write decision (one Haiku call), reads unchanged. Cost bounded: classify writes only, cheap model, cache. Document real numbers in `/eval`.

### Migrations
SQLite ledger schema via **Alembic** (never hand-edit schema). Cedar policies + YAML config are version-controlled files (git is their change history).

### AI product specifics (prompt-versioning · eval · tracing)
- **Prompt versioning:** risk-classifier prompt in `prompts/risk_classifier.yaml`, versioned.
- **Eval harness:** labeled `(tool call → expected risk)` set incl. **adversarial / prompt-injection** cases; optimize for **recall on destructive** calls (a false-negative is the dangerous failure). Run in `/eval`.
- **Tracing:** every LLM call traced (input hash, model, score, latency, cost) **into the same audit ledger** — so the AI's own decisions are auditable and verifiable.

## Structure

**Shape:** `src`-layout Python package `gatekeeper`, ports-&-adapters (hexagonal), dependencies inward.
Full map in [`STRUCTURE.md`](STRUCTURE.md).

- **Code** (`src/gatekeeper/`): `transport/` (MCP I/O) · `gateway/` (PEP pipeline) · `domain/` (pure logic) ·
  `ports/` (interfaces) · `adapters/` (identity·policy·ledger·upstream·llm — only layer with SDK imports) ·
  `schemas/` (typed DTOs) · `audit/` (verify) · `approval/`+`ai/`+`prompts/` (M2) · `infra/` · `config/` (loader) ·
  `db/` (migrations) · `cli/` (Typer → `gatekeeper`).
- **Deployment config** (root `config/`): `platform.yaml` (engine knobs + adapter selection) ·
  `product.yaml` (business knobs) · `upstreams.yaml` (the any-server registry) · `identities.yaml` (dev map).
  Policy in `policies/gatekeeper.cedar`. **Prompts** versioned at `src/gatekeeper/prompts/*.yaml`.
- **Root scaffolding present:** README · SECURITY · CHANGELOG (`[Unreleased]`) · CONTRIBUTING · LICENSE ·
  `.gitignore` (covers `.env*`) · `.env.example` (names only) · `.gitleaks.toml` · `.pre-commit-config.yaml` ·
  `Makefile` · `pyproject.toml` (dev/prod split) · `tests/{unit,integration,adversarial}` · `docs/{design,features}` · `examples/`.
- **No-hardcoding chain:** `.env` → `config/*.yaml` → `config/loader.py` (typed) → adapters by config key.
- **Git:** initialized on `main` (no commits yet — commit happens when you choose).

> ### ⏯ RESUME MARKER — next session
> **Done:** Vision ✅ · Scope ✅ · Plan ✅ · Architecture ✅ · Structure ✅.
> **Next phase:** **`/foundation`** — make the walking skeleton actually RUN: install deps, wire the typed
> config loader + structured logging, scaffold Alembic, stand up a CI that mirrors the bootstrap, and prove
> `gatekeeper --help` + secret-scan work. **Nothing is committed yet** — first commit can land in /foundation.
> **How to resume:** fresh session → run **`/playbook`** (re-orients from this file) or **`/foundation`** directly.

## Foundation

The walking skeleton **runs end-to-end** and the auto-layer (lint/format/types/secret-scan/dep-vuln/CI)
is wired. Evidence below is from real local runs (Python 3.13, `.venv`); the GitHub Actions green run
requires a push (see resume marker).

**Runs end-to-end?** Yes — `gatekeeper health` is the health path:
- valid key → **exit 0**, renders a config table + emits a structured JSON `health ok` log.
- (proof the binary path works, not just functions in isolation.)

**Config flows (no dead config) — verified HOW:** `health` reads values **back at runtime** from every
source and displays them: `env`/`log_level` (`.env`), `ledger.path` + `hash_algo=hmac-sha256` + the five
`adapters` (`platform.yaml`), `1` upstream (`upstreams.yaml`), `3` identities (`identities.yaml`).
A unit test (`test_config_loads_and_values_flow`) asserts the same, so dead config is caught in CI.

**Guards — fail-loud on misconfig, fail-closed on security (shown):**
- Missing/placeholder/short `GATEKEEPER_HMAC_KEY` → boot **refuses**, `health` exits **2** with a clear
  message + JSON error log. Proven live and by `test_guard_refuses_weak_or_short_hmac_key` (parametrized:
  empty, `changeme`, placeholder, too-short) + `test_health_fails_closed_without_key`. The HMAC key
  guards ledger integrity (ADR-003), so an insecure boot is impossible by construction (`boot()` is the
  single entrypoint that always runs the guard).
- Missing config dir / unparseable YAML → `ConfigError` (fail-loud), not a silent default.

**Structured logging + observability hook:** JSON-line logging to stderr (stdlib `JsonFormatter`, no
stray prints). Error-reporter/tracing seam exists behind a port (`infra/tracing.py`,
`LoggingErrorReporter`; swap for Sentry/OTel later) — "never raises" so it can't take down the request path.

**Migrations:** Alembic scaffolded; `env.py` derives the SQLite URL from `config/platform.yaml`
(no hardcoded connection string). `alembic upgrade head` → **exit 0**. First real migration (the
LedgerEntry table) is created in `/contracts`.

**Auto-layer (deterministic checks):**
- pre-commit: trailing-whitespace/eof/yaml/toml/large-files/private-key, **ruff** (lint) + **ruff-format**,
  **gitleaks** (secret-scan), **pip-audit** (dep-vuln, `pre-push` stage).
- **Dependabot** wired day-one (`pip` + `github-actions`, weekly), tightly-coupled packages **grouped**
  (pydantic, web-stack, data-stack, dev) so they bump in one PR.
- **CI** (`.github/workflows/ci.yml`), blocks merge on red, 2 jobs:
  `quality` (install prod deps → ruff + format + **mypy** → `alembic upgrade head` → pytest →
  **build wheel + clean-install + `gatekeeper health` smoke** with a runtime-generated key = prod-bootstrap parity) ·
  `security` (**gitleaks** + **pip-audit**, fail-closed on a CVE).
  *(No container yet — for a pip-distributed tool the prod artifact is the wheel. A proven, CI-built
  Dockerfile will land when the deferred "real deployment" trigger fires, per Scope; we don't carry an
  untested one in the meantime.)*

**Async / event loop:** N/A for M1 (no model download / blocking first-use). M2 LLM + upstream I/O are
async via `httpx` behind adapters; the rule is recorded so it isn't violated later.

### Local evidence (this session)
| Check | Result |
|---|---|
| `ruff check .` | All checks passed |
| `ruff format --check .` | 30 files already formatted |
| `mypy` | Success: no issues in 28 source files |
| `pytest -q` | **9 passed** |
| `gatekeeper health` (valid key) | exit 0 + config table + JSON log |
| `gatekeeper health` (no key) | exit 2, fail-closed |
| `alembic upgrade head` | exit 0 |
| `pip-audit` (local) | ⚠️ blocked by sandbox TLS — but **passes green in CI** |
| GitHub Actions CI | ✅ **green** — both jobs pass (PR #1, merged to `main`) |

### Proven on CI (not just locally)
- The full `pip install -e .` **resolved the complete dependency graph** (cedarpy, mcp, fastapi, sqlalchemy…)
  on a clean Ubuntu runner — the dep graph is sound.
- The **dep-vuln gate fail-closed for real**: pip-audit caught `pip 26.1.1` (PYSEC-2026-196) and the build
  went red until pip was upgraded — proof the gate works, not just that it's wired.
- CI surfaced 4 issues local runs couldn't (pytest import-mode, missing ledger dir, gitleaks PR permission,
  the pip CVE); all fixed before merge.

### Honest gaps
- `pip-audit` still can't run in this local sandbox (TLS cert interception) — but it runs green in CI, so
  it's covered.
- No governance business logic yet — that's `/contracts` → `/build` M1.1 (by design).

## Contracts

All boundaries are typed (no raw dicts/text cross a seam), the persisted schema is built by a migration
and **proven to match the code**, and every unit/scale is pinned on both sides.

### Typed domain models (`src/gatekeeper/schemas/`)
| Model | Boundary | Notes |
|---|---|---|
| `Principal` | IdentityResolver → gateway | `id`, `role`, `tenant` (frozen/immutable after resolution) |
| `ToolCall` | transport → gateway | `call_id` (UUID4, idempotency key), `upstream`, `tool`, `arguments`, `action_kind` |
| `ToolResult` | upstream → gateway | `ok`, redacted `summary` (never raw output) |
| `Decision` | policy → gateway | `verdict` (allow/deny), `reason`, `risk` 0..1 \| None |
| `RiskAssessment` | LLM (M2) → gateway | `risk` 0..1, `is_write`, `reason` |
| `LedgerEntry` / `VerifyResult` | gateway ↔ ledger | the audit record + `verify` output |
| Enums | everywhere | `Verdict{allow,deny}`, `ActionKind{read,write,unknown}` (string-valued) |

### Port contracts (`src/gatekeeper/ports/`, typed `Protocol`s)
`IdentityResolver.resolve` · `PolicyEngine.evaluate` · `LedgerStore.{append,read,get,verify}` ·
`UpstreamClient.forward` (async) · `LLMProvider.classify` (async, M2). Each documents its **fail-closed**
contract (unknown token → raise; policy/ledger error → deny; classifier error → require approval).

### Persistence + migration (the wedge table)
- ORM `db.models.LedgerEntryRow` ↔ DTO `schemas.LedgerEntry`, **field-for-field**.
- **Migration `0001_create_ledger`** creates `ledger_entry` (append-only audit log) with
  `entry_hash` **UNIQUE** + indexes on `call_id`, `ts`, `tenant`, and `(principal, ts)`.
- **Schema↔code proven:** `alembic check` → *"No new upgrade operations detected"* (zero drift), and an
  integration test runs the real migration into a temp DB and asserts DB columns == ORM columns.
- Chain (implemented in /build): `entry_hash = HMAC-SHA256(key, prev_hash + canonical_json(entry-without-hashes))`, `prev_hash` of entry #1 = `GENESIS_HASH` (64 zeros).

### Boundary units / scale (agreed both sides)
| Field | Unit / scale | Pinned where |
|---|---|---|
| `risk` | float **[0.0, 1.0]** (0=safe, 1=dangerous) | model `ge/le` + test asserts `config product.yaml approve_threshold ∈ [0,1]` |
| `ts` | **UTC** ISO-8601 string | `LedgerEntry.ts` doc |
| `payload_hash`/`entry_hash`/`prev_hash` | lowercase hex, **64 chars** (HMAC-SHA256) | `HASH_HEX_LEN`, `GENESIS_HASH` |
| `verdict`, `action_kind` | closed enums | `schemas.enums` |

### Versioning · idempotency · tenancy · PII
- **Versioning:** every row carries `schema_version` (=1); models are additive-only going forward; ports evolve additively.
- **Idempotency / natural key:** `call_id` (UUID4 minted at ingress) identifies one intercepted call.
- **Tenancy (isolation seam):** every persisted entity carries `tenant` (default `"default"`; multi-tenant deferred).
- **PII / sensitive data:** raw `arguments` and raw upstream output are **NEVER persisted** — only a
  keyed `payload_hash` + a redacted `result_summary`. Full-capture is a deferred, config-gated option
  for non-sensitive upstreams only. (`identities.yaml` tokens are dev-only fakes, gitleaks-allowlisted.)

### Evidence (this phase)
`ruff`/`mypy` clean (38 files) · **20 tests pass** (10 new: model+boundary+migration) ·
`alembic upgrade head` applies · `alembic check` = no drift · schema==code asserted in an integration test.

## Build log
_(unfilled — `/build`)_

## Dev-complete
_(unfilled — `/dev-check`)_

## Tests
_(unfilled — `/test`)_

## Evaluation
_(unfilled — `/eval`)_

## Ship log
_(unfilled — `/ship`)_

## Learnings
_(unfilled — `/learn`)_
