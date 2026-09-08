# STRUCTURE.md — GateKeeperAI codebase map

A **ports & adapters** layout in `src`-layout form, so the installed package is the tested package.
Dependencies point inward (transport → gateway → domain); only `adapters/` may import an external SDK.

```
gatekeeper/
├── README.md  STRUCTURE.md  SECURITY.md  CHANGELOG.md  CONTRIBUTING.md  LICENSE
├── pyproject.toml          # package metadata + deps; dev tools under [dependency-groups]
├── Makefile                # install / demo / init / doctor / serve / tail / verify / test / lint
├── Dockerfile              # cloud-neutral image; configured by environment, no baked overlay
├── .env.example            # the variable NAMES (secrets + overrides). `gatekeeper init` writes .env
│
├── config/                 # ── what you edit (data, not code) ──
│   ├── upstreams.yaml      #   the governed servers: how to launch each, which tools are writes
│   ├── identities.yaml     #   demo tokens -> principal -> role (refused on a public bind)
│   ├── platform.yaml       #   how the gateway runs; every knob has a GATEKEEPER_* env var
│   └── product.yaml        #   how a tool name is guessed to be a write when unannotated
├── policies/gatekeeper.cedar   # the rulebook: role x read/write -> allow; deny by default
│
├── src/gatekeeper/         # ── the package ──
│   ├── cli/                #   `gatekeeper` init · doctor · serve · tail · verify · show · stats
│   ├── transport/          #   MCP bindings: stdio (one identity per process) and HTTP (per-request)
│   ├── gateway/            #   the pipeline: identity -> classify -> policy -> audit -> forward -> audit
│   ├── domain/             #   pure logic: read/write classification, error types
│   ├── ports/              #   the interfaces: IdentityResolver, PolicyEngine, LedgerStore, UpstreamClient
│   ├── adapters/           #   the implementations (the only SDK imports)
│   │   ├── identity/       #     static_token · oidc
│   │   ├── policy/         #     cedar
│   │   ├── ledger/         #     sqlite (WAL, single writer) + the keyed-HMAC hash chain + auto-migrate
│   │   └── upstream/       #     mcp_client: launches governed servers with a minimal environment
│   ├── schemas/            #   typed DTOs: ToolCall, ToolResult, Principal, Decision, LedgerEntry
│   ├── config/             #   loader: .env + YAML + GATEKEEPER_* overrides, project-root paths
│   ├── db/                 #   engine setup + Alembic migrations (shipped inside the package)
│   └── infra/              #   JSON logging, metrics, alerts
│
├── deploy/container/entrypoint.sh   # `exec gatekeeper serve`
├── scripts/                # demo.py · demo_enterprise.py · deploy_azure.sh · probe_hosted.py · windows/*.bat
├── examples/               # demo_file_server.py — the governed demo target (read + write tools)
├── tests/                  # unit · integration · adversarial · golden (RBAC dataset) · eval (benchmarks)
└── docs/                   # getting-started · deploy · features · runbooks · glossary · internal/
```

## Two decisions a reviewer will ask about

- **`src`-layout, package `gatekeeper`.** It is a pip-installable tool, so the package lives under
  `src/` and tests run against the installed artifact. Migrations ship inside the package, which is
  why a fresh checkout or container needs no separate migrate step.
- **`config/` at the root vs `src/gatekeeper/config/`.** Deployment config is data a security
  engineer edits, so it sits where it is obvious; the typed loader that reads it is code and lives in
  the package. Secrets are in neither, only in `.env` or the deployment environment.

## Where a value comes from

Process environment → `.env` in the project root → `config/*.yaml` → built-in defaults. Relative
paths resolve against the project root (the parent of the config folder), so the gateway behaves the
same whether you run it from a shell or an MCP host launches it from elsewhere.
