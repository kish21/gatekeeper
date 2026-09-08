# STRUCTURE.md — GateKeeperAI codebase map

A **ports & adapters** layout in `src`-layout form, so the installed package is the tested package.
Dependencies point inward (transport → gateway → domain); only `adapters/` may import an external SDK.

```
gatekeeper/
├── README.md  STRUCTURE.md  SECURITY.md  CHANGELOG.md  CONTRIBUTING.md  LICENSE
├── pyproject.toml          # package metadata + deps; dev tools under [dependency-groups]
├── Makefile                # install / demo / init / doctor / serve / tail / verify / test / lint
├── Dockerfile              # cloud-neutral image; configured by environment, no baked overlay
├── docker-compose.yml      # local: the gateway + a Postgres audit ledger + the desk, one command
├── .env.example            # the variable NAMES (secrets + overrides). `gatekeeper init` writes .env
│
├── config/                 # ── what you edit (data, not code) ──
│   ├── upstreams.yaml      #   the governed servers: how to launch each, which tools are writes
│   ├── identities.yaml     #   demo tokens -> principal -> role (refused on a public bind)
│   ├── platform.yaml       #   how the gateway runs; every knob has a GATEKEEPER_* env var
│   └── product.yaml        #   which writes are held for a human, for how long; write-name patterns
├── policies/gatekeeper.cedar   # the rulebook: role x read/write -> allow; deny by default
│
├── src/gatekeeper/         # ── the package ──
│   ├── cli/                #   `gatekeeper` init · doctor · serve · ui · pending · approve · deny
│                           #     · tail · verify · show · stats · export · archive · rotate-key
│   ├── ui/                 #   the desk: approvals, activity, trust, servers (one HTML page + a JSON API)
│   ├── transport/          #   MCP bindings: stdio (one identity per process) and HTTP (per-request)
│   ├── gateway/            #   the pipeline: identity -> classify -> policy -> [hold for a human] -> audit -> forward -> audit
│   ├── domain/             #   pure logic: classification, argument attributes, risk, approver rules
│   ├── ports/              #   the interfaces: IdentityResolver, PolicyEngine, LedgerStore, UpstreamClient, ApprovalQueue
│   ├── adapters/           #   the implementations (the only SDK imports)
│   │   ├── identity/       #     static_token · oidc
│   │   ├── policy/         #     cedar
│   │   ├── ledger/         #     sql: sqlite (one machine) or postgres (durable, many replicas)
│   │   ├── approval/       #     sql queue of held writes, decided from another process
│   │   └── upstream/       #     mcp_client: launches governed servers with a minimal environment
│   ├── schemas/            #   typed DTOs: ToolCall, ToolResult, Principal, Decision, LedgerEntry
│   ├── config/             #   loader: .env + YAML + GATEKEEPER_* overrides, project-root paths
│   ├── db/                 #   engine setup + Alembic migrations (shipped inside the package)
│   └── infra/              #   JSON logging, metrics, alerts, held-write notifications
│
├── deploy/container/entrypoint.sh   # `exec gatekeeper serve`
├── scripts/                # demo.py · demo_company.py · demo_enterprise.py · agent.py · deploy_azure.sh · probe_hosted.py · windows/*.bat
├── examples/               # governed demo targets: demo_file_server + twins of sharepoint, jira, github, database, mail
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
