# PRODUCT.md — GateKeeperAI

> The shared spine of this product. Each playbook phase fills its own section.
> **AI product? YES** (uses an LLM to risk-score/classify tool calls → the AI-security layer applies downstream.)

> ### ⏯ RESUME MARKER — next session
> **Done:** Vision…Contracts ✅ · **Build #1 ✅ — tamper-evident ledger** · **Build #2 ✅ — transparent
> governed MCP proxy (M1.1)** · **Build #3 ✅ — Identity + RBAC policy-as-code / Cedar (M1.2)** ·
> **Build #4 ✅ — Tamper-evidence gate + `show` (M1.3)** · **Build #5 ✅ — Config-driven any-server +
> `seed-demo` (M1.4)** (a **real third-party** MCP server `mcp-server-time` governed by **config-only**
> edits, **zero gateway code** — live-verified E2E: 6 tools re-exposed, allow/read/audited, `verify` OK,
> `show` full decision; `seed-demo` implemented; one bad upstream skipped not fatal; **91 tests**,
> code+security reviewed clean). See `#Build log` +
> [docs/features/config-driven-any-server.md](docs/features/config-driven-any-server.md).
> **➡ M1.4 was the last M1 slice — all of M1 is now built.**
> **`/dev-check` ✅ PASSED (2026-06-09):** M1 is **development-complete**. Re-run this session on HEAD
> `ead36d9`: 93/93 tests green (0 skipped, incl. real-subprocess integration + adversarial), ruff/format/
> mypy/alembic-drift clean, CI both jobs green, no god-files, no hardcoding, **no scope creep** (M2 dirs
> are empty seams). Every M1 exit criterion proven by a named live-path test. **Phase confidence 93%.**
> See `#Dev-complete` for the full evidence checklist + honest gaps.
> **`/test` ✅ DONE (2026-06-09):** dedicated unit/integration/regression + adversarial + golden pass.
> **112 tests green (0 skipped, +19 this slice)**, ruff/format/mypy-strict clean, CI runs `pytest` on
> every push+PR (real merge gate). New: a **golden RBAC eval dataset** (`tests/golden/`) vs the shipped
> Cedar policy; adversarial **classification→RBAC evasion** surfaced + pinned as a tracked limitation
> (unannotated destructive tool → readonly allowed; mitigation = annotation, backstop = M2 LLM
> classifier); **read access-scoping** asserted (`read(principal=)` isolates, `get()` not scoped =
> documented). Prompt-injection/jailbreak (OWASP-LLM) deferred to M2 (no M1 LLM path). See `#Tests`.
> **`/eval` ✅ DONE (2026-06-09):** M1 measured **good on its core goal** — north-star coverage =
> **100% / 0 bypass**, RBAC golden **13/13**, tamper-evidence detects+pinpoints all 4 attack classes,
> **0 operational failures** (112 tests + 4,800+ harness calls), LLM cost **$0**. **One honest miss:**
> added gateway latency **p95 ≈ 21.5 ms vs the ~10 ms ADR-001 budget (~2×)** — root-caused to the
> SQLite durable-commit fsync (Cedar 0.4 ms + HMAC 0.03 ms are negligible; 2 commits/allowed call
> dominate). **Quantified fix:** WAL journal → append ~2 ms ⇒ p95 within budget (a one-line config
> PRAGMA, queued as an M2/follow-up slice, NOT silently fixed here). New artifacts: reproducible
> harness `tests/eval/bench_governance_latency.py` + config gate `platform.yaml perf.overhead_p95_ms`.
> **Phase confidence 88%.** See `#Evaluation` for the full breakdown + carried gaps.
> **`/ship` ✅ DONE (2026-06-09):** M1 Evaluation shipped — deep `/code-review` (fixed a percentile
> off-by-one; **made the component + WAL tables reproducible** via `--diagnose`; added a logging-bias
> caveat), security clean (no `src/`/auth/data change), docs reconciled, **PR
> [#22](https://github.com/kish21/gatekeeper/pull/22) merged**, CI green. See `#Ship log`.
> **`/learn` ✅ DONE (2026-06-10):** M1 cycle closed with an evidence-based retro. North-star measured
> **good** (100% coverage / 0 bypass · RBAC 13/13 · tamper 4/4 · 0 op-failures, all CI-gated); honest
> caveat — **no external user / live dashboard exists** (pre-deployment portfolio build), so those two
> criteria are partial-by-construction, not skipped. **Decided-next = BUILD M2** (evidence-backed: the
> classification→RBAC evasion gap *proves* deterministic rules are insufficient → validates the LLM
> classifier), **vision-aligned, zero scope creep**. Harvested a generic toolkit lesson (*derive perf
> budgets from a measured dominant-cost, never a guessed ADR number*). **Cycle confidence 82%.** See
> `#Learnings`.
> **⏸ M2 DELIBERATELY DEFERRED ~60 days → target ~2026-08-08 (product decision, NOT drift).** M2's
> trigger ("M1 core proxy + ledger demoed & integrity-verified") is **met**, but the build is
> intentionally time-boxed for later. M1 stays the shipped baseline until then. **⚠ `/learn` correction:
> the previously-claimed one-time reminder for the target date does NOT exist** (verified: no scheduled
> task / cron job) — re-arm it before relying on it. **→ RE-ARMED ✅ 2026-06-12:** one-time scheduled
> task `gatekeeper-m2-resume-reminder` fires 2026-08-08 09:00 — **verified present + enabled in the
> scheduler itself**, not just noted. **Next phase (on resume ~Aug 2026):** **M2.1** — write/risk
> classification (LLM classifier behind a provider adapter) → **M2.2** human-in-the-loop write-approval
> gate; **first M2 slice should also land the WAL ledger PRAGMA** (closes the `/eval` latency miss) +
> close the classification→RBAC evasion gap. Resume via `/playbook` or `/architect` for the M2 stack.
> **🚀 M3 CYCLE KICKED OFF (2026-06-12, docs-only session):** new market evidence — an **anonymized
> enterprise platform-requirements specification (2026-06)** for exactly this product category — fired
> triggers this file already documented (`#Scope` SSO/OIDC · `#Plan` infra/deploy · the unfinished M1
> "stdio + **HTTP**" transport item) → **Milestone 3 "Enterprise deployment readiness" inserted before
> M2's box**: **M3.1** HTTP transport → **M3.2** OIDC identity (generic adapter, Entra-first) →
> **M3.3** container + Azure-first hosted deploy → **M3.4** observability surface → **M3.5**
> connector-onboarding runbook. **M2 unchanged** (same scope, ~2026-08-08 box, reminder ARMED — see
> above). Cloud posture: agnostic core, Azure-first proof. See `#Learnings` Decided-next amendment,
> `#Scope` M3 table (quoted triggers), `#Plan` M3 slice table.
> **`/architect` M3.1 ✅ DONE (2026-06-12, docs-only):** HTTP-transport decisions recorded in
> `#Architecture` → *M3.1 addendum* — MCP **Streamable HTTP** via the official SDK, mounted in a
> **FastAPI + uvicorn single-worker** app (`/mcp` + `/healthz`); per-request `Authorization: Bearer`
> resolved + recorded **in the pipeline**, not the transport (ADR-008); **single worker = ledger
> single-writer held by construction** (ADR-007); **loopback-by-default, refuse non-loopback bind
> without explicit config ack** (ADR-009); ADR-006 re-evaluated → still deferred (loopback). New config
> knobs only (`transport.http_path/http_allow_non_loopback/http_allowed_origins`); no new adapter, no
> migration, no new secret. Aspirational +<~5 ms p95 transport overhead → re-measure in `/eval`.
> **How to resume (next session): run `/build` for M3.1 — HTTP transport** (decisions above; shared
> proxy-surface builder refactor out of `stdio_server.py`; exit criterion in `#Plan` M3 table). One slice
> per session: each via `/architect` → `/build` → `/ship`; `/security-review` on M3.1/M3.2 (auth surface).
> **Dev setup:** `.venv` has full deps incl. the `demo` extra (`pip install -e ".[demo]"`). Demo:
> `export GATEKEEPER_HMAC_KEY=$(openssl rand -hex 32)`, `export GATEKEEPER_AGENT_TOKEN=dev-token-alice-REPLACE-ME`,
> `make migrate`, `gatekeeper seed-demo`, `gatekeeper serve` (drive with an MCP client → demo_file_server + the
> `time` server), then `gatekeeper tail` / `verify` / `show <call_id>`. **Note:** the `time` upstream needs
> the `python` on PATH to have `mcp-server-time` (activate `.venv`), else it's logged+skipped (gateway still serves).
> RBAC tokens: `dev-token-bob-REPLACE-ME` = readonly (write → denied), `dev-token-root-REPLACE-ME` = admin.
> **Bundled fix (shipped with this PR):** the pre-existing `McpUpstreamClient.aclose()` cross-task
> cancel-scope teardown bug — each upstream session's anyio lifecycle is now pinned to one dedicated
> task (`_SessionRunner`/`_run_session`), so `aclose()` is task-safe even when a session was first
> opened inside a forward's child task. Independent of M1.4's `_build_tool_index` skip; verified by
> `tests/integration/test_upstream_lifecycle.py` + a clean live shutdown.
> **How to resume:** fresh session → run **`/playbook`** or **`/dev-check`** directly.

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

**In-scope — Milestone 3 "Enterprise deployment readiness" (pulled in 2026-06-12 — triggers FIRED, quoted per row; builds NOW, before M2's ~2026-08-08 box)**
> **Evidence:** an **anonymized enterprise platform-requirements specification (2026-06)** for exactly
> this product category — governed MCP orchestration with enterprise identity, hosted deployment,
> observability, and connector onboarding. Items move out of Deferred **only because their own
> pre-documented triggers fired** (the anti-drift rule), not because they became appealing.
> Full reasoning: `#Learnings` → Decided-next amendment (2026-06-12).

| In-scope item (M3) | Customer outcome (security engineer can…) | Fired trigger (quoted from this file) |
|---|---|---|
| **HTTP transport** (M3.1) | …point a network-reachable agent at the gateway and get the identical governed pipeline | Not a pull — *"Transparent MCP proxy (stdio + HTTP transport)"* is **already in-scope M1**; only stdio was built, so this finishes unfinished scope |
| **OIDC identity adapter** (M3.2 — generic OIDC behind the existing `IdentityResolver` port; Entra ID proven first) | …plug in the company IdP: real tokens → principal + role via a configured group→role map, no static dev tokens | Deferred row *"SSO / OIDC identity integration — Trigger: A real deployment needs enterprise identity (replaces token→role stub)"* → **FIRED** by the 2026-06 enterprise platform requirements |
| **Container + hosted cloud deploy** (M3.3 — cloud-neutral container; Azure-first proof) | …run the gateway as a hosted control plane: secrets via environment, ledger on persistent storage | `#Plan` checklist *"Infra / deploy … Trigger: a real hosted deployment"* → **FIRED** (same evidence; deployment subscription available) |
| **Observability surface** (M3.4) | …see live platform health: calls, allow/deny rates, governance-overhead p95 vs budget, one alert hook | `#Learnings` watch item *"**Not** instrumented: a live usage dashboard / alerting — **trigger: a real deployment**"* → fired by M3.3 itself |
| **Connector-onboarding runbook + 3rd real credentialed connector** (M3.5) | …onboard a credentialed third-party MCP server from the runbook alone — config + `.env` only | Serves the locked north-star secondary (*"time-to-govern a new MCP server = config-only, < a few minutes, zero code"*) at enterprise grade, proven on a ServiceNow-class connector |

**Deferred (real external trigger required to pull in)**
| Deferred item | Trigger that would justify it |
|---|---|
| Web dashboard / approval UI (vs CLI) | A user/reviewer can't operate via CLI, or the approval flow needs non-engineers |
| ~~SSO / OIDC identity integration~~ → **moved to in-scope M3.2 (2026-06-12)** | Trigger *"A real deployment needs enterprise identity (replaces token→role stub)"* → **FIRED** by the anonymized enterprise platform requirements (2026-06); see In-scope M3 above |
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

### Milestone 3 — Enterprise deployment readiness (inserted 2026-06-12; **builds NOW, before M2's box**)
> **Why out of number order:** M2 was scoped and committed first and keeps its number and its
> ~2026-08-08 time box (deliberate, unchanged). M3 was pulled in on 2026-06-12 by **fired,
> pre-documented triggers** — an anonymized enterprise platform-requirements spec (2026-06); each
> trigger is quoted in the `#Scope` M3 table, full reasoning in the `#Learnings` Decided-next
> amendment — and it is the enterprise platform layer *underneath* M2's approval feature, so it is
> built first. **Cloud posture: agnostic core, Azure-first proof** (generic OIDC adapter + standard
> container run anywhere; Azure is where it is deployed/proven first; a GCP deploy guide is an
> optional follow-up slice, no code change). Stack choices (MSAL vs PyJWT+JWKS, Container Apps vs
> AKS, dashboard tech) are **deliberately deferred to each slice's `/architect` step** —
> benchmarked-2026, OSS-first, per the playbook. One slice ≈ one build session.

| # | Slice | Testable exit criterion ("done when…") |
|---|---|---|
| **M3.1** | **HTTP transport** (finish the M1 in-scope item; FastAPI/uvicorn already deps) | An agent governs calls **over HTTP** (loopback) through the **same** pipeline; stdio unchanged; calls over both transports recorded + `verify`-clean. ADR-006 note: the network-exposure trigger for sender-constrained tokens is documented at the boundary. |
| **M3.2** | **OIDC identity adapter** (generic OIDC behind the existing `IdentityResolver` port — `ports/identity.py` unchanged; Entra ID proven first) | A real Entra-issued token (JWKS signature, audience, expiry validated) resolves to principal + role via a configured group→role map; expired/forged token **fail-closed**; `adapters.identity: oidc` is a pure config swap; `static_token` stays the dev default. |
| **M3.3** | **Containerize + first cloud deploy** (cloud-neutral container; Azure-first proof) | Dockerfile + deploy guide; gateway runs on Azure (Container Apps), ledger on persistent storage; a local agent makes a governed call against the **cloud** gateway; `verify` clean; secrets via environment, none in image/config. GCP guide = optional follow-up slice, no code change. |
| **M3.4** | **Observability surface** | An operator can see live platform health: calls, allow/deny rates, governance-overhead p95 vs the 10 ms budget; one alert hook (e.g. on verify-failure / deny-spike). |
| **M3.5** | **Connector-onboarding runbook + 3rd real connector** | A fresh operator onboards a **credentialed** third-party MCP server (ServiceNow-class) from the runbook alone — config + `.env` only; runbook includes a service-mapping + SLA template for reuse. |
| **M3 exit (gate)** | — | A network agent authenticates via a real IdP token to a **hosted** gateway; its calls are governed + `verify`-clean end-to-end; platform health is observable; a fresh operator can onboard a credentialed connector from docs alone. `/security-review` clean on the identity + transport slices (auth surface). |

### Milestone 2 — AI write-safety (committed; **deliberately deferred to ~2026-08-08**)
> **Deferral (product decision 2026-06-09, not drift):** M1 exit + `/eval` are verified, so M2's
> trigger is **met** — but M2 is **intentionally time-boxed ~60 days out (target ~2026-08-08)**.
> **Reminder ARMED 2026-06-12** (one-time scheduled task `gatekeeper-m2-resume-reminder`, fires
> 2026-08-08 09:00 — verified in the scheduler; the earlier finding that none existed is closed).
> M1 remains the shipped baseline until then; **M3 (above) builds in the meantime**. The **first M2 slice
> should also land the WAL ledger PRAGMA** (closes the `/eval` latency miss) and **close the
> classification→RBAC evasion gap** (the LLM classifier is its backstop, ADR-005). Both are recorded
> in `#Evaluation` / `#Build log` "Known limitations".

| # | Slice | Testable exit criterion |
|---|---|---|
| **M2.1** | Write/risk classification | Each call is classified read vs write and assigned a risk score (static rules + an **LLM classifier behind a provider interface**). A destructive call scores high, a read scores low; the classification + rationale are recorded in the ledger. |
| **M2.2** | Human-in-the-loop write-approval gate | A high-risk/write call is **held pending** human approve/deny; approved → forwarded, denied → blocked; the approver identity + decision are recorded in the **verifiable** ledger. Fail-closed: no approval ⇒ no execution. |
| **M2 exit (gate)** | — | A write call demonstrably blocks until a human approves; classifier evaluated for accuracy + prompt-injection resistance; full chain still `verify`-clean. |

### Out-of-scope (referenced, NOT scheduled — pull in only on trigger)
Web dashboard/approval UI, multi-tenant, rate-limit/budgets, policy-editor UI, transports beyond
stdio+HTTP — triggers in `#Scope`. *(SSO/OIDC and infra/deploy left this list on 2026-06-12 — their
documented triggers **fired**; see Milestone 3 above.)*

### Concern-area coverage checklist (production-readiness)
| Area | When | Note / trigger |
|---|---|---|
| **Security** | **NOW** | This *is* a security product: authN, RBAC, fail-closed, tamper-evident audit are core. `/security-review` on the decision+ledger path is an M1 gate. |
| **AI-specific** | **NEXT (M2)** | LLM risk classifier behind a provider adapter; prompt-injection resistance + classifier eval. Trigger: M2 start. |
| **Observability** | **NOW** | Structured logging + the audit ledger IS the observability spine; every call traced end-to-end. **M3.4 (added 2026-06-12)** layers the live operator health surface on top (calls, allow/deny rates, p95 vs budget, alert hook). |
| **Developer-experience** | **NOW** | Config-driven, CLI, drop-in proxy — directly serves the north-star secondary (time-to-govern a new server). |
| **Testing** | **NOW** | Unit (policy engine, hash-chain), integration (real upstream MCP server), adversarial (tamper attempts, RBAC bypass, no-bypass paths). |
| **Infra / deploy** | **M3 (trigger FIRED 2026-06-12)** | Was LATER with trigger *"a real hosted deployment"* — fired by the 2026-06 enterprise platform requirements → containerize + Azure-first hosted deploy = **M3.3**. Multi-tenant stays deferred (its own trigger unfired). |
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

### M3.1 — HTTP transport decisions (added 2026-06-12, `/architect`)
**Slice goal (from `#Plan`):** an agent governs calls **over HTTP (loopback)** through the **same**
pipeline; stdio unchanged; calls over both transports recorded + `verify`-clean; the ADR-006
network-exposure trigger documented *and enforced* at the boundary.

| Decision | Choice | Why (one line) |
|---|---|---|
| Wire protocol | **MCP Streamable HTTP** via the official SDK's `StreamableHTTPSessionManager` (`mcp` 1.27.2 — already a dep, verified installed) | The current MCP spec transport (the older SSE transport is deprecated); same rule as stdio — never reinvent JSON-RPC framing. |
| ASGI host | **FastAPI app + Uvicorn, single worker** — MCP mounted at a config-driven path (default `/mcp`), plus a `/healthz` liveness route | Both already deps and already the documented stack-table row; `/healthz` feeds M3.3 container probes; the M2 approval API + M3.4 observability endpoints get a natural home. |
| Identity over HTTP | `Authorization: Bearer <token>` per **request** — transport extracts it via the SDK request context (`RequestContext.request`, verified present in 1.27.2); the **pipeline** resolves + records it | Transport stays logic-free (the PEP stays `GatewayPipeline`); identity-deny stays a ledger entry; **multi-principal on one gateway** becomes possible (new vs stdio's one-token-per-process). |
| Exposure posture | **Loopback by default; refuse a non-loopback bind** without an explicit config ack; SDK DNS-rebinding protection (`TransportSecuritySettings` allowed-hosts/origins) on | Fail-closed: bearer tokens are replayable (ADR-006) — the exposure trigger is enforced in code, not just documented. |
| Sessions | SDK defaults (stateful; streaming responses) | No fired trigger for stateless/json-response mode; both stay config-addable later with no interface change. |

**New ADRs (load-bearing):**
- **ADR-007 — Single-worker serving preserves the ledger's single-writer assumption *by construction*.**
  `SqliteLedgerStore.append` is a **sync** read-prev-hash → insert (verified in code) with a documented
  single-writer assumption; HTTP introduces concurrent sessions for the first time. Under **one** uvicorn
  worker/event loop a sync append contains no `await`, so two appends can never interleave — the hash
  chain cannot race, with **no new lock layer**. Enforced: `serve` exposes no `workers` knob; M3.3
  deploys **1 replica** (record it there). *Rejected:* asyncio/DB locking + multi-worker (complexity with
  no fired scale trigger; the real answer at that trigger is the deferred Postgres ledger). *Trade-off
  carried, not silent:* the sync durable-commit blocks the event loop (the measured ~21.5 ms p95 from
  `/eval`); the WAL `PRAGMA` fix stays queued for the first M2 slice.
- **ADR-008 — Authn enforcement lives in the pipeline; the transport only extracts credentials.**
  A `tools/call` with a missing/invalid bearer still reaches `pipeline.handle`, which **records the
  identity-deny in the ledger, then refuses** (identical to the stdio per-call path) — never a silent
  transport-level 401 for a tool call, so "every call accounted for" holds over HTTP. The non-call
  surface (initialize / `tools/list`) resolves the token **fail-closed** so an unauthenticated client
  cannot enumerate tools. This per-request seam is exactly where OIDC (M3.2) and DPoP/mTLS (ADR-006)
  later drop in with **no pipeline change**. *Rejected:* validating tokens in ASGI middleware (moves
  authz logic into transport and loses the ledger record for denied tool calls).
- **ADR-009 — Fail-closed network exposure.** Default bind `127.0.0.1:8765` (already in
  `platform.yaml`); a non-loopback `transport.http_host` **refuses boot** unless
  `transport.http_allow_non_loopback: true` is set explicitly, which logs the ADR-006 bearer-replay
  warning. TLS is **not** implemented in-process — it terminates at the cloud ingress in M3.3.
  *Rejected:* silently binding `0.0.0.0` (fail-open) · in-process TLS now (no trigger; cert plumbing
  belongs to the deploy slice).
- **ADR-006 re-evaluated at this slice (as the `#Learnings` amendment requires):** still **deferred** —
  M3.1 is loopback-only by ADR-009, so the "exposed beyond a trusted local/loopback boundary" clause has
  **not** fired yet; it comes into actual view at M3.2 (real OIDC) / M3.3 (hosted), where it must be
  re-evaluated again.

**Config (no hardcoding):** reuses `transport.{mode,http_host,http_port}` (already present in
`platform.yaml`); adds `transport.http_path` (default `/mcp`), `transport.http_allow_non_loopback`
(default `false`), `transport.http_allowed_origins` (default none ⇒ rebinding protection stays active).
CLI: `gatekeeper serve` reads `transport.mode`; `--transport stdio|http` is an explicit per-invocation
override. **No new secrets** (the bearer arrives in a request header; nothing token-shaped lands in YAML
or code).

**Adapters / externals:** **none new** — HTTP is a second *inbound* binding of the same low-level MCP
`Server`; stdio and HTTP share one proxy-surface builder (tool index + list/call handlers, refactored
out of `stdio_server.py` into a shared module) so governance behavior cannot drift between transports.
Resilience: uvicorn lifespan shutdown → `runtime.aclose()` (same teardown as stdio); per-upstream
timeouts/retries unchanged; the SDK's `session_idle_timeout` stays available as a config knob if needed.

**Perf budget (derived, not guessed):** the governance-overhead budget is **unchanged** (identical
pipeline; `perf.overhead_p95_ms: 10`, with the known fsync miss carried). New and **explicitly
aspirational** (no probe run this docs session — per the harvested budget rule): HTTP transport adds
**< ~5 ms p95 over stdio on loopback** (ASGI dispatch + localhost hop) — **re-measure in `/eval`**
with the existing `bench_governance_latency.py` pattern before treating it as fact.

**Patterns / anti-patterns (this slice):** applied — same chain-of-responsibility PEP behind a second
thin transport binding; shared surface-builder (don't repeat the proxy surface). Avoided — authz-in-
transport (god transport) · fail-open bind · reinventing protocol framing · premature horizontal
scaling (multi-worker with a single-writer ledger would be a correctness bug dressed as scalability).

**Migrations:** N/A (no schema change). **AI specifics:** N/A (no LLM path in this slice).

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

> **Sequencing note:** within M1, the **ledger (wedge)** was built before the proxy — a deliberate
> resequence of the plan's M1.1 slice. Rationale: the ledger is self-contained, fully demonstrable on
> its own (`gatekeeper verify`), and de-risks the hardest/highest-value part. The MCP proxy that feeds it
> is the next `/build`. Still within M1 scope.

| Feature | DoD incl. security met? | How verified (evidence) | Doc |
|---|---|---|---|
| **Tamper-evident audit ledger** (keyed-HMAC hash-chain `LedgerStore`: append/read/get/verify + `verify`/`tail` CLI) | ✅ append-only · fail-closed HMAC key · detects edit/delete/reorder/insert/wrong-key · PII-safe (hash+redacted) · tenant filter · no secret in code | **Live:** migrate→append 3→`verify` OK+head (exit 0)→raw-SQL tamper→`verify` TAMPERED@seq=2 (exit 1). **Tests:** 29 (9 new) incl. tamper/delete/wrong-key. **/security-review:** no findings ≥8. **/code-review:** cleanups applied. ruff+mypy clean; `alembic check` no drift. | [docs/features/ledger.md](docs/features/ledger.md) |
| **Transparent governed MCP proxy (M1.1)** — stdio proxy (`gatekeeper serve`) re-exposing upstream tools by original name; pipeline identity→classify→audit-before→forward→audit-outcome; `StaticTokenResolver`, `McpUpstreamClient`, `ActionClassifier`, `build_runtime` | ✅ no ungoverned bypass (forward only inside `handle`) · audit-before-act fail-closed · fail-closed identity (deny recorded, token never echoed, `serve` refuses unauth) · every call audited (`validate_input=False`) · PII-safe (args→`payload_hash`, output→status-only summary, `raw` excluded) · no secret in code | **Live (real CLI+subprocess):** `serve` ← MCP client → `demo_file_server`: list_tools(4)→write+read transparent (`live-proof`)→`tail` 4 entries→`verify` OK exit 0; unauth token & no-key → exit 2. **Tests:** 58 (28 new) unit+integration(real upstream)+adversarial(unauth/append-fail/tamper). **/code-review (high):** 6 findings fixed (session-open race, unaudited-pre-handler, output-in-ledger, double-boot, audit-drift, canonicalization). **/security-review:** no findings ≥8. ruff+mypy(strict) clean. | [docs/features/proxy.md](docs/features/proxy.md) |
| **Identity + RBAC policy-as-code — Cedar (M1.2)** — `CedarPolicyEngine` (policy adapter) inserted as the PDP at pipeline step 3 (replaces M1.1 allow-all); evaluates (role × action × tool) against version-controlled `policies/gatekeeper.cedar` → allow/deny+reason; `PolicyDenied` error; `_build_policy` config-selected; transport surfaces deny | ✅ **authorized per role×action×tool from config (no hardcoded rule)** · readonly-write **denied+recorded+not forwarded**, allowed call passes — **both** decisions recorded · fail-closed eval (default-deny, unknown-role/NoDecision/any error → DENY) · fail-loud load (missing/empty/unparseable/zero-statement policy → refuse boot) · no policy/entity injection (structured-dict request, escaped EUIDs) · no token leak in reason/log · pipeline stays SDK-free | **Live (real composition root + CLI):** bob/readonly `write_file`→**DENY** (1 entry, no disk write), bob `list_dir`→ALLOW, alice/operator write→ALLOW (decision+outcome); `tail` verdicts, `verify` OK exit 0, `health` shows `policy=cedar`. **Tests:** 77 (19 new) — unit `test_policy` (RBAC matrix, fail-loud×4, fail-closed eval, escaping) + pipeline deny-once-not-forwarded; adversarial readonly-write-denied on **real Cedar+ledger** (verify ok); integration denied-write-leaves-no-file on **real upstream**. **/code-review (high, 2 finders):** no contract bugs; 2 hardening items taken (zero-statement load guard, eval-error log detail). **/security-review:** no findings ≥8 (9/10, verified vs live engine). ruff+mypy(strict) clean. | [docs/features/rbac.md](docs/features/rbac.md) |
| **Config-driven any-server + operator CLI (M1.4)** — registered a **real third-party MCP server** (`mcp-server-time`, `demo` extra) in `config/upstreams.yaml` → governed with **zero `src/gatekeeper/` change**; implemented `gatekeeper seed-demo` (non-destructive prep + run recipe); hardened `_build_tool_index` to skip a bad upstream instead of crashing | ✅ **M1.4 exit met:** a **2nd, different** server governed by **config-only** edits (config + a dependency extra; no gateway code) · authenticated → RBAC (read→allow) → transparent relay → **2 chained ledger entries**, `verify` OK, Cedar reason names `time::get_current_time` · `seed-demo` exit 0/2, idempotent, **prints role only never token** · one unavailable upstream **logged+skipped, not fatal** (no ungoverned bypass — its tools aren't published) · Windows-console-safe (ASCII; `[demo]` not eaten as markup) · `yaml.safe_load`; subprocess arg-vector (no shell) | **Live (real `serve` ← MCP client → real 3rd-party server):** 6 tools re-exposed across 2 upstreams; `get_current_time`+`convert_time` via gateway → real JSON relayed, **allow/read/audited**; `tail` shows `time:*`; `verify` OK exit 0 + head; `show <call_id>` full decision. `seed-demo` rendered both governed upstreams + roles + recipe, seeded sandbox. **Tests:** 91 (+9) — integration vs **real `mcp-server-time` subprocess** (allow+audited+verify+lists tools), `seed-demo` unit ×6 (no-leak, idempotent, fail-loud, ASCII, drift-guard), proxy resilience (bad upstream skipped). **/code-review (high, 2 finders):** no correctness bugs; took the 1 real finding (pip-audit didn't scan the `demo` extra → fixed in CI security job). **/security-review:** no findings ≥8 (token-leak, path-traversal, cmd-injection, governance-bypass, unsafe-deser all traced clean). ruff+mypy(strict) clean (49 files). | [docs/features/config-driven-any-server.md](docs/features/config-driven-any-server.md) |
| **Tamper-evidence gate + `show` (M1.3)** — gate confirming the hash-chain `verify` holds against the now-RBAC ledger (allow+deny verdicts) + implemented `gatekeeper show <call_id>` (operator inspection of one recorded decision via existing `LedgerStore.get`; no new port method) | ✅ **M1.3 exit met:** `verify` passes intact & **pinpoints `seq`** on alter/delete/insert — confirmed on a ledger of RBAC verdicts · `show` exit 0/1/2 (found/not-found/misconfig), fail-loud/closed via reused `_opened_ledger` · **no token/key leak** (entry holds principal/role + HMAC digests only; key in `.env`) asserted by test · PII-safe by construction · no injection (parameterized `call_id`) · Windows-console-safe (`box.ASCII`) · reuse-not-reinvent | **Live (real CLI + SQLite):** seed allow+deny via real append-chain → `tail` both → `show <allow>`/`<deny>` full decision (deny.prev_hash == allow.entry_hash) → `show <missing>` exit 1 → `verify` OK exit 0 → raw-SQL flip deny→allow → `verify` **TAMPERED@seq=2** exit 1 (show still renders the altered row → read/verify split). **Tests:** 82 (5 new `test_cli_show`: found-allow/deny, not-found→1, no-leak, console-safe). **/code-review (high):** no findings. **/security-review:** no **new** vuln ≥8 — the one ≥8 (`get()` not tenant-scoped) is the **pre-existing documented limitation** consistent with `tail`, tied to the deferred multi-tenant trigger. ruff+mypy(strict) clean. | [docs/features/tamper-evidence.md](docs/features/tamper-evidence.md) |
| **Showcase demo + `.env` upstream secrets + MCP-host hardening (Session-0 batch)** — `scripts/demo.py`: one-command 5-beat narrated governance story on the **real** `build_pipeline()` wiring (operator read ALLOW → readonly write DENY → real 3rd-party server zero-code → `verify` OK → deliberate tamper CAUGHT), hermetic (ephemeral HMAC key + temp ledger/sandbox), + `.bat` launchers + `docs/HOW-IT-WORKS.md`/svg; **`{from_env: NAME}`** — `upstreams.yaml` env values reference secrets by NAME, resolved at launch via `secret_source()` (`.env` overlaid by real env) and injected into the launched server, so credentialed 3rd-party servers are governed with **no secret in YAML**; composition split `build_pipeline()` (injectable) / `build_runtime()`; MCP-host hardening (boot errors → **stderr** so stdout stays pure JSON-RPC, upstream launchers pinned to `sys.executable`, unwritable ledger dir → `ConfigError` + cwd hint) | ✅ secrets never in YAML / logs / ledger (resolved at launch only; **fail-closed** on missing/malformed refs) · demo drives the **identical governed path** `serve` uses (no parallel demo pipeline) · **no new scope** — serves the in-scope operator surface + config-driven registration; the secrets **non-goal honored** (reference via config/env, never store) | **Live:** demo end-to-end on the real pipeline (allow → deny → zero-code 3rd-party → `verify` OK → tamper caught); secret injection proven by a **live-subprocess** integration test; field-found MCP-host failures reproduced then fixed. **Tests: 127 (+15)** — secret-resolution unit + live-subprocess injection, serve-stderr regression, launcher pinning, ledger-dir error mapping; re-run green at push time. **/security-review** (secret path): no findings. ruff+mypy clean. | [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md) |

| **HTTP transport (M3.1)** — MCP **Streamable HTTP** binding of the same pipeline: shared proxy-surface builder (`transport/surface.py`) refactored out of stdio so the two transports CANNOT drift; FastAPI+uvicorn **single-worker** app (`/mcp` exact-path route + `/healthz`); per-request `Authorization: Bearer` extracted by the transport, **resolved + recorded in the pipeline** (ADR-008, multi-principal on one gateway); `serve --transport stdio\|http` | ✅ **M3.1 exit met** · ADR-007 single-writer held by construction (no `workers` knob exists) · ADR-008: forged/missing bearer on `tools/call` → **ledgered `<unauthenticated>` DENY** then refused (never a silent 401); unauthenticated `tools/list` → **empty** (no enumeration; empty-not-raise is load-bearing — the SDK's call_tool wrapper refreshes its tool cache through the list handler, a raise there would skip the ledgered deny; found by the adversarial test) · ADR-009: non-loopback bind **refuses boot** without `http_allow_non_loopback: true` ack (ack logs ADR-006 bearer-replay warning); unknown hostnames = non-loopback (fail-closed); SDK DNS-rebinding protection ON (rebound Host → 421) · config-only knobs (`http_path`/`http_allow_non_loopback`/`http_allowed_origins`), no new secret, token never logged | **Live (real `gatekeeper serve --transport http` ← real MCP client):** healthz 200 · 6 tools across both upstreams (incl. 3rd-party `time`) · alice read ALLOW transparent · bob write **DENY (Cedar default-deny)** · ledger holds prior **stdio** entries (seq 2–4) + these **HTTP** entries (seq 5–7) in ONE chain → `verify` OK 7 entries. **Tests: 150 (+19, 0 skipped)** — unit seams (exposure guard ×9, bearer parse ×8, knob flow, CLI fail-loud) + integration vs **real uvicorn + real MCP client + real subprocess upstream** (same-pipeline+verify-clean, forged-bearer ledgered deny, Host-header 421). ruff+format+mypy(strict) clean. | [docs/features/http-transport.md](docs/features/http-transport.md) |

**Known limitations (recorded, not silent):** tail-truncation undetectable by a bare chain (mitigation:
`verify` emits head hash to pin out-of-band; full anchoring deferred) · `get()` not tenant-scoped (safe
today: UUID call_ids + single tenant) · single-writer append assumption · **classification→RBAC evasion**
— an unannotated destructive tool whose name matches no `write_detection` pattern is classified read, so
`readonly` may call it (mitigation today: explicit `writes:` annotation; backstop: M2 LLM classifier per
ADR-005). All four are tracked by asserted tests — see `#Tests`.

## Dev-complete

**M1 development-complete gate — PASSED.** Every box ticked **with re-run evidence** (verified this
session on the exact `main` HEAD `ead36d9`, not assumed). The earlier "TAMPERED@seq=1" seen while
spot-running `verify` was a **harness artifact** (a random HMAC key pointed at a stale scratch
`./.gatekeeper/audit.db` written under a different key) — i.e. the **wrong-key detection firing
correctly** (matches `test_wrong_key_cannot_verify`), not a product defect.

### Exit-criteria checklist (evidence, not "done")
- [x] **Every core-scope feature has a `#Build log` row, runs, and met its DoD (incl. security).**
  Re-verified per slice below.
- [x] **No hardcoding · prompts externalized · contracts typed · schema↔code consistent · CI green.**
  Hardcoding scan of `gateway/`+`domain/`+`transport/` → no secrets/URLs/tokens/thresholds (only a
  docstring match); adapters config-selected from `platform.yaml` (proven live by `health`).
  `alembic check` → *"No new upgrade operations detected"* (zero schema↔code drift). Prompts in
  `src/gatekeeper/prompts/risk_classifier.yaml` (versioned; M2-only, not on the M1 path).
- [x] **No oversized god-files; secret-scan + dep-vuln clean.** Largest source file = 277 lines
  (`cli/app.py`); 2219 total across 49 files — single-responsibility held. `gitleaks` + `pip-audit`
  (with `.[demo]`) **green in CI** on HEAD (run `27235863456`, both jobs `success`). *(Both scanners
  are CI-only locally — `gitleaks` not installed; `pip-audit` blocked by the sandbox's TLS
  interception, as documented in `#Foundation`.)*
- [x] **Scope re-check — no creep.** M2 dirs are empty seams, not built features: `approval/` (5 lines),
  `ai/` (6), `adapters/llm/` (6) are stubs; `ports/llm.py` (17) is a declared `Protocol`. Nothing from
  the OUT-OF-SCOPE list (dashboard, SSO, multi-tenant, rate-limit, policy-UI, extra transports) exists.
- [x] **Every "done" records HOW it was verified.** All 5 `#Build log` rows carry an evidence column;
  re-confirmed below by independently re-running the named live-path tests.

### Per-feature coverage (re-run this session)
| M1 slice | Runs? | DoD incl. security — verified by |
|---|---|---|
| **M1.1 Transparent governed proxy** | ✅ | `test_proxy.py` (real `demo_file_server` subprocess through the gateway); `test_audit_store_failure_blocks_the_forward` (audit-before-act fail-closed); `test_unauthenticated_call_is_denied_recorded_and_never_forwarded` (identity fail-closed, no bypass). |
| **M1.2 Identity + RBAC (Cedar)** | ✅ | `test_readonly_role_writing_is_denied_recorded_and_never_forwarded` + `...reading_is_allowed_and_forwarded` on **real Cedar + real ledger** — both decisions recorded, deny not forwarded. Policy lives in `policies/gatekeeper.cedar` (config, not code). |
| **M1.3 Tamper-evidence + `verify`** | ✅ | `test_verify_ok_on_intact_chain` (OK), `test_verify_detects_field_tamper` / `..._deletion` / `test_wrong_key_cannot_verify` (pinpoint `seq`); live binary reproduced wrong-key → `TAMPERED@seq=1`. |
| **M1.4 Any-server (zero code) + operator CLI** | ✅ | `test_governs_real_third_party_server_with_zero_code` + `test_lists_third_party_tools...` vs a **real `mcp-server-time` subprocess** (0 skipped). Operator binary live: `health` (exit 0, config from all sources), no-key (exit 2 fail-closed), `show <missing>` (exit 1). |

### Auto-layer (re-run locally this session)
| Check | Result |
|---|---|
| `ruff check .` | All checks passed (exit 0) |
| `ruff format --check .` | 67 files already formatted |
| `mypy` (strict) | Success: no issues in **49** source files |
| `pytest -q` | **93 passed, 0 skipped** (21.4s) — incl. real upstream subprocess tests |
| `alembic check` | No new upgrade operations (zero drift) |
| GitHub Actions CI (HEAD `ead36d9`) | ✅ both jobs green: `lint·migrate·test` + `secret-scan·dep-vuln` |

### Honest gaps (recorded, not silent)
- **Security scanners are CI-only locally** — `gitleaks` not on PATH; `pip-audit` blocked by sandbox
  TLS. Mitigation: both pass green in CI on the exact gated commit. No local-only blind spot in the
  product, only in the local sandbox.
- **Python 3.13 local vs 3.12 CI** — suite passes on both; no version-specific failure observed.
- **No fresh holistic `/security-review` re-run here** — the working tree is **clean (no diff to
  review)**, and each slice already carries a clean `/security-review` (no finding ≥8) in `#Build log`
  / `#Ship log`. The adversarial/prompt-injection + authz-bypass security cases run next in **`/test`**.
- **Pre-existing documented limitations carried forward** (not regressions): `get()` not tenant-scoped
  (safe today: single tenant + UUID call_ids), tail-truncation needs out-of-band head-hash anchoring,
  single-writer append assumption — all tied to deferred triggers in `#Scope`.

**Phase confidence: 93%.**
- **Solid (tested/verified):** 93/93 tests green incl. real-subprocess integration + adversarial RBAC/tamper; lint/format/mypy/alembic-drift clean; CI both jobs green on HEAD; live binary paths (health/fail-closed/show) exercised; every M1 exit criterion proven by a named test; no scope creep; no god-files; no hardcoding.
- **Risky/untested:** security scanners verified only via CI (not locally); no fresh end-to-end `/security-review` this phase (clean tree → no diff); adversarial security depth is `/test`'s remit, not yet exhaustively run.
- **To raise it:** run **`/test`** — the dedicated unit/integration/regression + adversarial (prompt-injection, authz/tenant-isolation) pass on the live path — and confirm the security scanners locally once outside the TLS-intercepting sandbox.

## Tests

**Pass run-this-session (HEAD `ead36d9` + this `/test` slice):** `ruff` + `ruff format --check` +
`mypy --strict` (49 src files) clean · **112 passed, 0 skipped** (+19 this phase). The suite is a
**real merge gate**: `.github/workflows/ci.yml` runs `pytest -q` on **every push to `main` AND every
pull_request**, alongside lint/format/mypy/alembic + a fail-closed security job (gitleaks + pip-audit)
— a red run blocks merge. Tests use **fake placeholder tokens** (`k*64` HMAC, `dev-token-*` ids,
gitleaks-allowlisted); **no real secrets**.

### Coverage by tier (the independent test plan)
| Tier | What it proves | Key files |
|---|---|---|
| **Unit** (isolated, ports faked) | hash-chain math; config-driven read/write classification; Cedar RBAC matrix + fail-loud load + fail-closed eval + EUID-escaping; pipeline fail-closed invariants (audit-before-act, unknown-token denied, append-failure blocks forward, raw-args never persisted); contracts/migration parity; CLI `show`/`seed-demo` (no-leak, idempotent, console-safe) | `unit/test_{hashchain,classify,policy,pipeline,contracts,payload_hash,summarize,identity,cli_show,cli_seed_demo,foundation}.py` |
| **Integration** (real contracts) | gateway pipeline vs a **real `demo_file_server` subprocess** + **real `mcp-server-time` 3rd-party subprocess**; real Cedar engine; real SQLite ledger append/read/get/verify; Alembic schema↔code; upstream anyio-lifecycle teardown | `integration/test_{proxy,any_server,ledger,migration,upstream_lifecycle}.py` |
| **Adversarial / security** | unauthenticated call denied+recorded+never-forwarded; readonly-write denied+recorded+never-forwarded (real Cedar+ledger); audit-store-failure blocks forward; ledger tamper (alter/insert/remove/wrong-key) breaks `verify` and pinpoints `seq`; **classification→RBAC evasion** (below); **read access-scoping** (below) | `adversarial/test_{proxy_governance,governance_gaps}.py` |
| **Golden / eval** | the RBAC contract as a labeled dataset — known `(role, action, upstream, tool) → expected verdict` run against the **shipped** `policies/gatekeeper.cedar`; the M1 analog of the M2 risk-classifier eval | `golden/rbac_golden.yaml` + `golden/test_rbac_golden.py` |

### Live-path verified (tests passing ≠ it works)
The path the product actually runs is exercised end-to-end **through the real binary path**, not only
isolated units: `integration/test_proxy.py` and `test_any_server.py` drive the gateway as a real MCP
**server** (subprocess) with a real MCP **client** against real upstream MCP servers — list-tools →
call → transparent relay → 2 chained ledger entries → `verify` OK. The forward is reachable **only**
inside `GatewayPipeline.handle` after an audited ALLOW, so there is **no ungoverned bypass path**
(asserted by the unauthenticated + policy-deny + append-failure cases). Operator-binary live paths
(`health` exit 0, no-key exit 2 fail-closed, `show <missing>` exit 1) are exercised in `#Dev-complete`.

### Adversarial findings recorded this phase (honest, asserted — not surprises)
- **Classification→RBAC evasion (tracked M1 limitation).** Authorization keys off the *classified*
  `action_kind`. The M1 classifier is name-pattern + annotation based, so a destructive tool whose
  name matches none of `write_detection.name_patterns` (`create*/update*/delete*/write*/put*/exec*/
  run*/send*`) **and** carries no explicit `writes:` annotation — e.g. `drop_table`, `purge_*`,
  `truncate_*`, `remove_*` — is classified **read**, and a `readonly` role is therefore **allowed** to
  call it. It is still authenticated, classified, and **provably audited** (no call slips past *audit*);
  what slips is the *write-intent gate*. `test_unannotated_destructive_tool_slips_past_readonly_rbac`
  pins this; `test_annotating_the_destructive_tool_closes_the_gap` proves the lever that exists **today**
  (an explicit `writes:` annotation → readonly denied + never forwarded) — i.e. it is a **config** gap,
  not a hole in the enforcement path. The architectural backstop is **M2's LLM risk classifier**
  (ADR-005, fails closed to human approval), which scores destructive calls regardless of name. When
  M2 lands, that test should flip to a deny — the built-in regression signal.
- **Read access-scoping.** `read(principal=…)` enforces within-tenant owner isolation (one principal
  cannot list another's entries — `test_read_is_scoped_by_principal`). `get(call_id)` is deliberately
  **not** principal/tenant-scoped (`test_get_is_not_principal_scoped_known_limitation`) — safe today
  (single tenant + unguessable UUID4 call_ids), tied to the **deferred multi-tenant** trigger in `#Scope`.

### Regression cases
- The bundled `McpUpstreamClient.aclose()` cross-task cancel-scope teardown fix is locked by
  `integration/test_upstream_lifecycle.py` (a session opened inside a forward's child task closes
  task-safe). The ledger wrong-key false-positive (the `#Dev-complete` "TAMPERED@seq=1" harness
  artifact) is locked by `unit/test_hashchain.py::test_wrong_key_cannot_verify`.

### AI / OWASP-LLM note (scoped honestly)
M1 has **no LLM on the request path** (`risk.enabled: false`), so prompt-injection / jailbreak (OWASP
LLM Top-10) cases are **M2's remit** — they belong with the risk classifier and will be added to the
golden/eval set in `/eval` → M2. The only M1 "injection" surface is the Cedar request: covered by
`test_policy.py::test_odd_tool_name_does_not_break_evaluation` (EUID escaping — an odd tool name can't
inject Cedar syntax). Raw tool arguments are hashed, never interpreted, and never persisted raw.

**Honest gaps:** (1) the classification→RBAC limitation above is real and **only** mitigated by config +
the (not-yet-built) M2 classifier — a security reviewer should treat unannotated upstreams as a risk
until M2; (2) security scanners (gitleaks/pip-audit) remain CI-only locally (sandbox TLS); (3)
prompt-injection/jailbreak eval is deferred to M2 by design (no M1 LLM path).

## Evaluation

**Verdict (honest):** M1 **meets its core quality goal** — the north-star *verifiable governance
coverage* — with **measured**, reproducible evidence; it **misses its secondary cost target** — the
ADR-001 latency budget — by ~2×, root-caused to durable audit commits, with a quantified fix. Both
are reported straight, neither rounded up. Measured this session on the exact `main` HEAD; every
number below is reproduced by a named test or the committed harness, not asserted.

### What "good" means here (tied to the vision)
M1 ships **no LLM on the request path** (`risk.enabled: false`), so there is **no classifier-accuracy
or prompt-injection metric to measure yet** (that is M2's eval, by design). M1's quality is therefore
**deterministic governance quality**, measured on three axes that map to the locked north-star
("every call authenticated + policy-decided + ledgered; 0 ungoverned bypass") and the ADR-001 cost
budget:
1. **Coverage / no-bypass** (the north-star itself) — is *every* call governed + provably recorded?
2. **Authorization correctness** (RBAC) — does the shipped policy decide allow/deny *correctly*?
3. **Cost** — LLM spend (n/a in M1) + the **added gateway latency** ADR-001 budgets (p95 < ~10 ms).

### Measured results

| Axis | Metric | Result | How measured (reproducible) | vs target |
|---|---|---|---|---|
| **Coverage / no-bypass** | calls authenticated → policy-decided → ledgered with 0 bypass | **100%** | named adversarial tests assert the forward is unreachable except after an audited ALLOW: unauthenticated → denied+recorded+never-forwarded; readonly-write → denied+recorded+never-forwarded (real Cedar+ledger); audit-append-failure → forward blocked | ✅ = 100% target |
| **RBAC correctness** | golden labeled `(role,action,upstream,tool)→verdict` vs shipped `policies/gatekeeper.cedar` | **13/13 = 100%** | `tests/golden/` run against the **real** Cedar engine; covers all 3 roles + both verdicts + fail-closed (unknown role/action → deny) | ✅ no policy drift |
| **Tamper-evidence** | `verify` detects + pinpoints alter / insert / delete / wrong-key | **4/4 detected, `seq` pinpointed** | `unit/test_hashchain.py` + `integration/test_ledger.py` + live binary (raw-SQL flip → `TAMPERED@seq=2`) | ✅ wedge holds |
| **Cost — LLM** | $/run | **$0.00** | no LLM call on the M1 path (`risk.enabled: false`) | ✅ (reads stay free, as designed) |
| **Cost — latency** | added gateway overhead, p95 (Cedar + HMAC + SQLite append, upstream excluded) | **p95 ≈ 21.5–22.9 ms · p50 ≈ 16 ms** | `tests/eval/bench_governance_latency.py` — real Cedar + classifier + keyed-HMAC + file-backed SQLite, zero-latency fake upstream, 1.5–3k samples/scenario | ❌ **over the ~10 ms budget (~2×)** |

**Operational failures (separated from quality, per eval-integrity):** **0.** Full suite **112 passed /
0 failed / 0 skipped**; the latency harness recorded **0 operational failures across 4,800+ calls** —
so the latency numbers are clean measurements, not contaminated by errored runs, and the quality
numbers above are not inflated by silently-dropped calls.

### The latency miss — root-caused, not hand-waved
The budget breach is **not** in the governance logic. Overhead attribution + the WAL lever are
**reproducible from the committed harness** — `python -m tests.eval.bench_governance_latency
--diagnose` (2k samples each; real Cedar / HMAC / file-SQLite):

| Component | p50 | p95 | share of overhead |
|---|---|---|---|
| Cedar RBAC eval | 0.23 ms | 0.36 ms | ~2% |
| keyed-HMAC ×2 (payload + entry) | 0.02 ms | 0.03 ms | ~0% |
| **SQLite append — current (FULL / rollback journal)** | **8.1 ms** | **9.9 ms** | **~98%** |

The entire overhead is the **synchronous commit fsync** (`PRAGMA synchronous=FULL`, rollback journal —
SQLite's safe default, **and the same engine config the prod ledger uses** — verified: both call
`create_engine` with no PRAGMA override). The **allow path commits twice** (audit-before-act
*decision* + *outcome*, ADR-003) → ~16 ms p50 / ~21 ms p95; the **deny path commits once** → ~9 ms p50
/ ~12 ms p95. This is a **real cost, not an artifact**: numbers are stable across runs, and the cause
is the *correct* durability posture for a tamper-evident audit ledger (you want the audit fsync'd
before you act). Absolute values are **hardware-dependent** (Windows dev box); the *structure*
(2 durable commits per allowed call) is portable.

**Quantified mitigation (measured by `--diagnose`, not yet implemented — deferred by choice):**
switching the ledger engine to **WAL journal mode** drops a single append from ~8 ms (p95 9.9) to
**p50 1.6 ms / p95 3.0 ms** (`synchronous=NORMAL`) or **p50 2.9 ms / p95 3.8 ms** (`synchronous=FULL`,
full durability kept) → allow-path (×2 commits) p95 **~6 ms / ~7.6 ms** — **within the 10 ms budget**,
with append-only + the HMAC chain unchanged. That is a one-line, config-driven `PRAGMA` on engine
setup. **Decision: do not relax the budget and do not silently fix it here** — record the honest miss
+ the lever; land WAL as an M2/follow-up build slice and let the harness gate it. (The budget knob now
lives in `config/platform.yaml` `perf.overhead_p95_ms`, so the gate is config, not hardcoded; the
harness exits non-zero on a regression.)

> **Measurement caveat (honest, biases *optimistic*):** the harness sets the `gatekeeper` logger to
> ERROR + injects a no-op reporter, so prod's per-call INFO log + observability hook (sub-ms each) are
> excluded — the real overhead is marginally *higher* than the numbers above, which only **deepens**
> the over-budget finding, never softens it.

### Scoring-bias check (AI-eval integrity)
N/A-by-construction for M1: the RBAC golden eval scores against **deterministic expected verdicts**
(no LLM judge), so there is no LLM-grader bias to audit. The LLM-judge / scoring-bias check belongs
with the **M2** risk-classifier eval (labeled `tool-call → expected risk`, recall-optimized on
destructive calls, incl. prompt-injection cases) — same dataset shape as the golden RBAC set, which
was built deliberately as its M1 analog.

### Baseline + regression gate (recorded)
- **RBAC**: the golden dataset **is** the recorded baseline — any policy edit that widens/narrows
  access fails `tests/golden/` naming the offending case (in CI on every push+PR).
- **Latency**: baseline = the ADR-001 budget in `config/platform.yaml` (`perf.overhead_p95_ms: 10.0`);
  `tests/eval/bench_governance_latency.py` is the reproducible harness + regression gate (exits
  non-zero above budget). It is **run-on-demand, not in the default CI gate** (microbenchmarks flake
  on shared runners) — an honest, documented choice, re-run each perf-sensitive change.

### Honest gaps (carried, not silent)
1. **Latency over budget (new, this phase)** — ~2× the ADR-001 target, fixable via WAL (above). Until
   then, M1's overhead is ~16 ms p50 per allowed call — fine for a governance control plane, but not
   yet at the stated budget.
2. **Absolute latency is hardware/OS-dependent** — measured on Windows; should be re-measured on the
   Linux/SSD CI target (likely faster fsync) before quoting a single canonical number.
3. **classification→RBAC evasion** (pre-existing, pinned) — an unannotated destructive tool is
   classified read, so `readonly` may call it; still **fully audited** (coverage intact), but the
   write-intent gate slips. Mitigation today = `writes:` annotation; architectural backstop = M2's LLM
   classifier (the test should flip to deny when M2 lands).
4. **No M1 AI-quality metric** — prompt-injection/jailbreak + classifier recall are M2's remit (no M1
   LLM path), deferred honestly.

### Confidence score — **88%**
- **Solid (measured/verified):** north-star coverage = 100% with 0 bypass (named adversarial tests);
  RBAC = 13/13 golden vs the real shipped policy; tamper-evidence detects+pinpoints all 4 attack
  classes; **0 operational failures** across the suite + 4,800+ harness calls; LLM cost $0; latency
  root-caused with a component breakdown + a *quantified* fix.
- **Risky/untested:** latency is **2× over budget** (the one real miss) and its absolute value is
  hardware-dependent; the classification→RBAC evasion is a known config-gated hole until M2; no
  AI-quality metric exists yet (by design).
- **To raise it:** land the **WAL** engine change + re-run the harness on the CI/SSD target to bring
  p95 under 10 ms (closes gap 1+2); ship **M2** to close the evasion gap + add the classifier eval
  (closes gap 3+4). None blocks the M1 wedge ("verifiable governance"), which is measured-good.

**Next phase:** **`/ship`** — deep fresh-eyes review, `/security-review`, reconcile docs to reality,
confidence score, open the PR, hand off. (The latency finding + WAL lever should be carried into the
PR description and queued as an M2/follow-up slice, not silently dropped.)

## Ship log

| Date | Shipped | Review + security | Docs reconciled? | CHANGELOG | Rollback / flag | PR |
|---|---|---|---|---|---|---|
| 2026-06-09 | **M1.3 — tamper-evidence gate + `gatekeeper show <call_id>`** (verify confirmed to pinpoint forgery on a ledger of RBAC verdicts; operator inspection of one recorded decision) | `/code-review` (high) no findings; `/security-review` no **new** vuln ≥8 (tenant-scoping = pre-existing documented limitation). Fresh-eyes live-path trace via the real binary. | ✅ `docs/features/tamper-evidence.md`, PRODUCT (#Build log + marker), README, CHANGELOG — match code | `[Unreleased]` (+ caught up missing M1.1/M1.2) | **Additive** (a stubbed command now works); no migration. Rollback = **revert PR #19**. Signal: CI green + `show` returns a decision on a real ledger. | [#19](https://github.com/kish21/gatekeeper/pull/19) |
| 2026-06-09 | **M1 Evaluation** — reproducible governance-overhead latency harness (`tests/eval/bench_governance_latency.py` + `--diagnose`), config-driven perf budget (`platform.yaml perf.overhead_p95_ms`), and the measured `#Evaluation` (coverage 100%/0 bypass · RBAC golden 13/13 · 0 op-failures · honest latency miss p95 ~2× budget, root-caused + WAL fix quantified) | **Deep `/code-review`** (3 parallel finders + verify): fixed the nearest-rank percentile off-by-one; **made the component + WAL tables reproducible** via `--diagnose` (was measured-but-not-in-repo — a real doc-integrity finding); added the logging-suppression caveat. **Security:** **no `src/` / auth / data / permission change** (test harness + non-secret config knob + docs); secret-scan clean. **No LLM path** (M1) → OWASP-LLM N/A, deferred to M2. | ✅ `PRODUCT.md#Evaluation` + marker, CHANGELOG; README/feature docs carry no perf claim (nothing to fix) — all match the reproducible harness | `[Unreleased]` (no public-API change → no semver bump) | **Docs + test-only + additive config**; gateway runtime behavior **unchanged** (the budget knob is read only by the harness). Rollback = **revert this PR**; no migration, no flag. Signal to watch: the harness p95 vs budget after the WAL slice lands. | [#22](https://github.com/kish21/gatekeeper/pull/22) |
| 2026-06-12 | **M3.1 `/architect` — HTTP-transport decisions (docs-only)** — `#Architecture` M3.1 addendum: MCP **Streamable HTTP** via the official SDK · FastAPI + uvicorn **single worker** (`/mcp` + `/healthz`) · **ADR-007** (single worker preserves the ledger single-writer assumption by construction) · **ADR-008** (authn decided + recorded in the pipeline; transport only extracts the per-request bearer) · **ADR-009** (loopback-by-default, non-loopback bind refuses boot without explicit config ack) · ADR-006 re-evaluated → still deferred (loopback) · config knobs only, no new adapter / migration / secret · transport-overhead budget recorded as explicitly **aspirational** (<~5 ms p95) → `/eval` re-measure | **Deep claims-verification review** — every factual claim traced to the installed SDK (`StreamableHTTPSessionManager`, `RequestContext.request`, `TransportSecuritySettings` in `mcp` 1.27.2), real code (`append()` is sync read-prev→insert, no `await`), and config (`transport.*`, `perf.overhead_p95_ms: 10.0`). `/security-review` **N/A** (docs-only; no `src/`/auth/data change; nothing token-shaped in the diff — gitleaks re-checks in CI) | ✅ addendum + resume marker; **CHANGELOG caught up** (M3 cycle entry incl. the missing #26 mention); README untouched — still accurately stdio-only, no false capability claim | `[Unreleased]` (docs-only → no semver bump) | **Docs-only**; no migration, no flag. Rollback = **revert PR #27**. Signal to watch: `/build` M3.1 must implement to these ADRs — ADR↔code divergence is the drift to catch | [#27](https://github.com/kish21/gatekeeper/pull/27) |
| 2026-06-12 | **Session-0 batch — narrated demo (`scripts/demo.py` + `.bat` launchers + `docs/HOW-IT-WORKS.md`/svg), `.env` upstream secret injection (`{from_env: NAME}` via `secret_source()`), MCP-host hardening (boot errors → stderr, `sys.executable` launcher pinning, ledger-dir `ConfigError` hint)** | Deep review + **`/security-review` of the secret path: no findings** (resolved values never logged/persisted; fail-closed on missing/malformed refs) — done in the build session; **127 tests re-run green at push time**; ruff+mypy clean | ✅ `docs/HOW-IT-WORKS.md` + README "See it in 30 seconds" + CHANGELOG ship **in the same PR**; `#Build log` row added same day (see `#Drift log` 2026-06-12 — found and closed) | `[Unreleased]` | **Additive feature + bugfixes**; no migration, no flag. Rollback = **revert PR #25**. Signal: CI green + demo runs end-to-end on a fresh checkout. | [#25](https://github.com/kish21/gatekeeper/pull/25) |

## Learnings

**Cycle:** M1 (Governed verifiable proxy) — Vision→Ship now complete; this is the post-M1 retro.
**Honest framing first:** GateKeeperAI is a **pre-deployment portfolio build** — there are **no external
users yet**. So the textbook `/learn` inputs (a live analytics dashboard, real user/usage telemetry)
**do not exist by construction**, and I will not fabricate them. The metric below is real and
**reproducibly measured**, but it is **CI/test-gated + ledger-native**, not a production dashboard. Two
of this skill's exit criteria (live-instrumented metric · external user signal) are therefore **honestly
partial** — recorded with the trigger that would complete them, not checked off.

### 1. Success metric + result (measured, not guessed)
**North-star — verifiable governance coverage** (every call authenticated → policy-decided → hash-chain
ledgered, 0 ungoverned bypass). Measured in `/eval` on the exact `main` HEAD, every number reproduced by
a named test or the committed harness:
| Metric | Result | Instrumented by (the standing gate) |
|---|---|---|
| Coverage / no-bypass | **100% / 0 bypass** | `tests/adversarial/test_proxy_governance.py` — forward unreachable except after an audited ALLOW; runs on **every push + PR** (CI merge gate) |
| RBAC correctness | **13/13 golden** | `tests/golden/` vs the shipped `policies/gatekeeper.cedar`; CI-gated — a policy edit that drifts authz fails loudly |
| Tamper-evidence | **4/4 attack classes detected, `seq` pinpointed** | `unit/test_hashchain.py` + `integration/test_ledger.py` + live binary |
| Operational failures | **0 / 4,800+ harness calls + 112 tests** | full suite + `tests/eval/bench_governance_latency.py` |
| Cost — LLM | **$0.00** | no LLM on the M1 path (`risk.enabled: false`) |
| Cost — latency (the one **miss**) | **p95 ≈ 21.5 ms vs ~10 ms budget (~2×)** | `bench_governance_latency.py --diagnose`; config gate `platform.yaml perf.overhead_p95_ms` |

**What counts as "instrumented" here (honest):** the **ledger is the per-call observability spine** (every
call → a verifiable audit record), and the **CI gates above are the standing instrumentation** — they
re-assert the metric on every change, which is the realistic analog of a dashboard for a pre-deployment
tool. **Not** instrumented: a live usage dashboard / alerting — **trigger: a real deployment.**

### 2. User signal (honest: no external user yet)
No production users → no external usage signal. The closest **real** signals incorporated:
- **Dogfood / live demo** — `seed-demo` + a **real third-party** `mcp-server-time` server governed
  end-to-end with **zero gateway code** (M1.4). This *exercised* the north-star secondary
  (time-to-govern config-only) rather than asserting it — the one "usage" proof that exists today.
- **Adversarial-test usage** surfaced two genuine signals (internal, not external): the
  **classification→RBAC evasion** gap and the **latency miss** — both fed straight into "decided next".
- **Unmet (honest):** an external user / reviewer / buyer driving the gateway. **Trigger to generate it:**
  a real deployment, or a portfolio reviewer running the demo against their own MCP server.

### 3. Retro — what worked · what to change
**Worked:**
- **Docs-driven spine** (`PRODUCT.md`) kept the build honest end-to-end; thin **vertical M1 slices** each
  landed on the **live binary path**, not just unit tests.
- **Ledger-first resequence** (built the wedge before the proxy) de-risked the hardest/highest-value part early.
- **Adversarial-first testing** surfaced the evasion gap and latency miss **as pinned tests**, not as
  silent holes; the eval reported the **2× latency miss straight** (root-caused + quantified WAL fix)
  instead of relaxing the budget — integrity held under a bad result.

**To change:**
- **Set perf budgets from a measured dominant cost, not a guessed number.** ADR-001 fixed p95 < ~10 ms
  **before** measuring the dominant cost (2× durable fsync commits per allowed call) → missed by 2×. The
  budget should have been derived from a quick dominant-cost probe, **or** marked explicitly *aspirational
  + re-measure in `/eval`*. (Harvested below.)
- **Name-pattern classification needs the semantic backstop it's already scoped for** — the evasion gap is
  acceptable only because it's pinned by a **flip-on-fix** test; M2's LLM classifier is the real close.
- **Don't claim a side-effect that isn't armed** — the prior resume marker stated an M2 reminder "is
  scheduled"; verification found **no scheduled task or cron job exists**. Stated obligations must be
  verified, not asserted (see the watch list).

### 4. Decided next — from evidence (re-checked vs vision + OUT-OF-SCOPE)
**Decision: BUILD M2, as already scoped — deliberately time-boxed to ~2026-08-08 (product decision, not drift).**
The evidence *backs* M2 rather than merely assuming it:
- The **classification→RBAC evasion** gap is **direct evidence** that pure deterministic name-pattern
  classification is insufficient — which is exactly the riskiest-assumption clause ("LLM risk-scoring adds
  enough value over pure deterministic rules"). So **M2.1 (LLM classifier behind `LLMProvider`)** is
  **evidence-backed**, not speculative.
- The **latency miss** dictates sequencing: the **first M2 slice lands the WAL `PRAGMA`** (quantified to
  bring allow-path p95 **~6–7.6 ms, under budget**) + closes the evasion gap. Then M2.1 → M2.2 (HITL
  write-approval).
- **Vision re-check:** M2 serves the AI-write-safety differentiator + the north-star; **nothing pulled
  from OUT-OF-SCOPE** (dashboard, SSO, multi-tenant, rate-limit all stay deferred with their triggers
  intact). **No drift.**
- **Kill/deprecate check:** nothing to kill — the M1 wedge is measured-good and M2 is evidence-backed.
  Honest null result, not a rubber-stamp.

**Deferred items keep their triggers** (unchanged): DPoP/mTLS → network-exposure; dashboard → non-CLI
user; SSO → real OIDC need; multi-tenant → shared instance; etc. (see `#Scope`).
*(Superseded in part by the 2026-06-12 amendment below — the SSO/OIDC and infra/deploy triggers have
since FIRED; the rest keep their triggers.)*

#### Amendment (2026-06-12) — new market evidence → insert Milestone 3 before M2's box
- **Evidence:** an **anonymized enterprise platform-requirements specification (2026-06)** describing
  exactly this product category — a governed MCP orchestration layer (RBAC, tamper-evident audit,
  approval workflows, connector architecture, enterprise identity/OIDC, hosted cloud deployment,
  observability) — analyzed as market evidence. It is the first concrete external demand signal this
  product has had, and it validates the `#Vision` buyer (the platform/security engineer) verbatim.
- **The triggers it fires are ones this file already documents** (the anti-drift test: pull a deferred
  item in only when *its own* recorded trigger fires — not because it became appealing):
  1. `#Scope` Deferred — *"SSO / OIDC identity integration — Trigger: A real deployment needs
     enterprise identity (replaces token→role stub)"* → **FIRED**.
  2. `#Plan` concern checklist — *"Infra / deploy … Trigger: a real hosted deployment"* → **FIRED**
     (the requirements are deployment-shaped and Azure-centric; a deployment subscription is available).
  3. `#Scope` M1 in-scope row reads *"Transparent MCP proxy (stdio + **HTTP** transport)"* but only
     **stdio** was built → **unfinished in-scope work**, not a new pull — M3 finishes it.
  4. The same evidence demands live operational visibility → completes the `§5` watch item *"Not
     instrumented: a live usage dashboard / alerting — trigger: a real deployment."*
- **Decision: insert Milestone 3 — "Enterprise deployment readiness" — and build it NOW, before M2's
  box.** Slices: **M3.1** HTTP transport · **M3.2** OIDC identity (generic adapter, Entra ID proven
  first) · **M3.3** container + Azure-first hosted deploy · **M3.4** observability surface ·
  **M3.5** connector-onboarding runbook + 3rd credentialed connector. **M2 is untouched** — same
  scope, same ~2026-08-08 box; M3 is the enterprise platform layer *underneath* M2's approval feature.
- **Cloud posture: agnostic core, Azure-first proof.** The code stays cloud-neutral by construction
  (generic OIDC adapter works with Entra/Okta/Google; a standard container runs anywhere); Azure is
  only where it is *deployed and proven first*, because the market evidence is Azure-centric and a
  subscription is on hand. A GCP deploy guide is an optional cheap follow-up, not a redesign.
- **Vision re-check (no drift):** M3 *deploys* the verifiable-governance gateway; it changes nothing
  about the wedge. Dashboard/approval UI, multi-tenant, rate-limiting, policy-editor UI **stay
  deferred** — their triggers have not fired. DPoP/mTLS (ADR-006) stays deferred too, but **both of
  its trigger clauses come into view during M3** (network exposure → M3.1/M3.3; real OIDC → M3.2) —
  re-evaluate it explicitly at each of those slices' `/architect` steps.
- Where the change landed: `#Scope` (items moved with their quoted fired triggers) · `#Plan`
  (M3 slice table with testable exit criteria) · resume marker (next session = `/architect` M3.1).

### 5. Observability + cost watch (the post-M1 watch, not a one-off)
- **Observability spine:** the hash-chained ledger (per-call verifiable audit) + structured JSON logs.
- **Perf gate:** `bench_governance_latency.py` against `perf.overhead_p95_ms` — **re-run on the Linux/SSD
  CI target** (M1 numbers are Windows-dev-box; eval gap #2) and **after the WAL slice** to confirm
  p95 < 10 ms. Run-on-demand (microbenchmarks flake on shared CI), documented.
- **Cost watch:** $0 in M1; **LLM cost monitoring begins at M2** (Claude Haiku, writes-only, cached). Set
  a per-write cost target as an M2 exit criterion.
- **⚠ Watch-list gap found this cycle:** the M2 trigger reminder (~2026-08-08) the marker claimed exists
  **does not** — no scheduled task/cron. Re-arm it (offered) so M2 isn't silently forgotten past its box.
  **→ CLOSED 2026-06-12:** one-time scheduled task `gatekeeper-m2-resume-reminder` armed, fires
  2026-08-08 09:00 — verified against the scheduler itself (listed, enabled, `nextRunAt` set), per the
  process fix below ("verify any scheduled/armed claim against the actual scheduler").

### 6. Reusable learning harvested (toolkit)
- **Graduating to the toolkit:** *"Derive a perf/cost budget from a measured dominant-cost probe — or mark
  it explicitly aspirational and commit to re-measuring in `/eval`. Never write a hard budget number into
  an ADR from a guess."* Generic across any product with a latency/cost target; home = the `/architect`
  (budget-setting) + `/eval` (budget-checking) phase skills in `product-playbook`. (Patched separately.)
- **Already captured (project memory):** the static name-pattern write-classification evasion lesson
  (`static-write-classification-is-evadable`) — kept project-scoped; its generic core (golden
  policy-eval dataset + flip-on-fix tests for known gaps) overlaps the above.
- **Process fix (project-local):** verify any "scheduled/armed" claim against the actual scheduler before
  writing it into a handoff marker.

**Cycle confidence: 82%.**
- **Solid:** north-star measured 100%/0-bypass + RBAC 13/13 + tamper 4/4 + 0 op-failures, all CI-gated;
  next move (M2, WAL-first) is evidence-backed and vision-aligned with zero scope creep.
- **Risky/partial (honest):** no external user signal and no live dashboard exist (pre-deployment build) —
  structurally unmet, not skipped; the latency miss is real until WAL lands; the evasion gap is open until M2.
- **To raise it:** get one real reviewer to drive the demo (external signal); land WAL + re-measure on
  Linux/SSD; ship M2.1 to flip the evasion test to deny.

## Drift log

> Cross-cutting `/drift-check` findings — dated rows on **confirmed** drift only (a check, not a phase).

| Date | Drift found | Type | Resolution |
|---|---|---|---|
| 2026-06-12 | Commit `b0957ee` (`feat/showcase-upstream-secrets-host-fixes`: narrated demo `scripts/demo.py` + runner `.bat`s, `docs/HOW-IT-WORKS.md`, **`.env` upstream secret injection `{from_env}`**, MCP-client/serve hardening, +15 tests → 127) exists in the repo but has **no `#Build log` / `#Ship log` row** — the spine is one commit behind the code. **Not scope creep**: each piece serves documented in-scope items (operator/demo surface, config-driven upstream registration; secrets referenced via env per the non-goal — never stored), and the branch's PR is not yet opened. | Code↔docs (build log stale vs code) | **Record, don't cut → CLOSED same day:** [PR #25](https://github.com/kish21/gatekeeper/pull/25) opened (127 tests re-run green at push) and the `#Build log` + `#Ship log` rows added in this kickoff branch. The gap never reached `main`. |
