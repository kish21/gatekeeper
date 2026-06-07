# STRUCTURE.md — GateKeeperAI codebase map

A clean **ports & adapters (hexagonal)** layout, `src`-layout so the installed package equals the tested
package. The rule: **dependencies point inward** (transport → gateway → domain), and the only layer
allowed to import an external SDK is `adapters/`. One folder = one concern; no god-files.

```
GateKeeperAI/
├── PRODUCT.md              # the product spine (vision→scope→plan→architecture/ADRs)
├── STRUCTURE.md            # this file — the codebase map
├── README.md  SECURITY.md  CHANGELOG.md  CONTRIBUTING.md  LICENSE
├── pyproject.toml          # package metadata + deps (prod) + [dependency-groups] dev + tool config
├── Makefile                # run targets: install / serve / verify / tail / test / lint / check / migrate / seed
├── .env.example            # secret NAMES only (copy → .env). .env is git-ignored.
├── .gitignore  .gitleaks.toml  .pre-commit-config.yaml   # hygiene + secret-scan
│
├── config/                 # ── DEPLOYMENT CONFIG (data, not code) — the no-hardcoding surface ──
│   ├── platform.yaml       #   engine/technical knobs: transport, adapter selection, resilience, log
│   ├── product.yaml        #   product/business knobs: fail-closed default, write-detection, M2 risk/approval
│   ├── upstreams.yaml      #   the registry — add ANY MCP server here to govern it (zero code)
│   └── identities.yaml     #   static token→principal→role map (M1 dev stub; FAKE tokens only)
├── policies/
│   └── gatekeeper.cedar    #   policy-as-code (RBAC allow/deny per role × tool) — analyzable (ADR-002)
│
├── src/gatekeeper/         # ── THE PACKAGE (code) ──
│   ├── transport/          #   speak MCP to the agent (stdio/HTTP). Protocol I/O only, no logic.
│   ├── gateway/            #   the PEP: pipeline identity→policy→[risk→approval]→audit→forward (fail-closed)
│   ├── domain/             #   pure domain logic + value objects. No I/O, no SDKs. Fully unit-testable.
│   ├── ports/              #   adapter INTERFACES (Protocols): Identity/Policy/Ledger/Upstream/LLM
│   ├── adapters/           #   concrete, config-selected impls of ports — ONLY layer that imports an SDK
│   │   ├── identity/       #     static_token (M1) | oidc (deferred)
│   │   ├── policy/         #     cedar
│   │   ├── ledger/         #     sqlite + hashchain (keyed-HMAC chain)
│   │   ├── upstream/       #     mcp_client (MCP client → real server)
│   │   └── llm/            #     claude + stub (M2)
│   ├── schemas/            #   typed DTOs crossing boundaries (ToolCall, ToolResult, LedgerEntry, Decision)
│   ├── audit/              #   tamper-evident ledger service + `verify` (the wedge)
│   ├── approval/           #   M2 human-in-the-loop write-approval gate
│   ├── ai/                 #   M2 LLM risk classification (uses the llm port; writes-only)
│   ├── prompts/            #   versioned AI prompts (YAML) — never inline. risk_classifier.yaml
│   ├── infra/              #   cross-cutting: structured JSON logging, resilience (timeout/retry/breaker)
│   ├── config/             #   typed config LOADER (loader.py) — reads .env + config/*.yaml
│   ├── db/                 #   persistence wiring + Alembic migrations (schema via migrations only)
│   └── cli/                #   operator CLI (Typer): serve/tail/verify/show/seed-demo  → `gatekeeper`
│
├── examples/               # governed targets for demos/tests (e.g. demo_file_server.py with read+write)
├── tests/                  # unit/ (mocked) · integration/ (real contracts) · adversarial/ (tamper/bypass/injection)
└── docs/                   # design/ (big-task design docs) · features/ (one per built feature)
```

## Why this shape (the two decisions a reviewer will ask about)

- **`src`-layout, package `gatekeeper`.** It's a pip-installable open-core tool, so the package is
  isolated under `src/` — you test the *installed* artifact, not loose top-level modules. (This is the
  modern Python-packaging default and the reason for `[tool.hatch.build.targets.wheel] packages`.)
- **`config/` (YAML data at root) vs `src/gatekeeper/config/` (the loader code).** Deliberate split:
  *deployment config is data a security engineer edits* (which servers, which roles, which thresholds)
  and lives at the root where it's obvious; the *typed loader that reads it* is code and lives in the
  package. Secrets are in neither — only in `.env`.

## The no-hardcoding chain
`.env` (secrets) → `config/platform.yaml` + `config/product.yaml` (knobs) → `src/gatekeeper/config/loader.py`
(typed load) → adapters selected by `adapters.*` keys. Change a server, a role, a threshold, or even the
policy/ledger/LLM implementation **without touching business logic**.
