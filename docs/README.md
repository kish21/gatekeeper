# docs/

Start with whichever of these matches you:

- **Showing it to a room?** [DEMO-COMPANY.md](DEMO-COMPANY.md): one assistant, five company
  systems, every write decided in the browser. Twelve minutes, with what to say at each step.
- **New to GateKeeper?** [WALKTHROUGH.md](WALKTHROUGH.md) is one afternoon with it, pasted from a
  real run: a write held, denied, approved, and the record verified. [USE-CASE-STORY.md](USE-CASE-STORY.md)
  tells the use case as a story, and [HOW-IT-WORKS.md](HOW-IT-WORKS.md) explains the parts.
- **Want to run it?** [getting-started.md](getting-started.md): install, `init`, `doctor`, connect your
  MCP host, read the audit trail.
- **Deploying it for the first time?** [deploy/first-deployment.md](deploy/first-deployment.md):
  the whole thing in one sitting, in plain English, with the reason for every step. Then
  [deploy/azure-container-apps.md](deploy/azure-container-apps.md) is the terse reference — every
  setting, every knob, and how the audit trail became durable. [SHOWCASE-AZURE.md](SHOWCASE-AZURE.md)
  is the hosted story plus a demo script for a customer call.
- **Deciding whether to buy it?** [WHAT-YOU-CAN-CONNECT.md](WHAT-YOU-CAN-CONNECT.md): the product
  in four sentences, the five systems that work today, what else you can put behind the guard, and
  the three things only you can decide. No code, no settings files.
- **A word you do not know?** [glossary.md](glossary.md).

Reference:

- **`features/`** — one page per built capability (what it does, how it is configured, its limits):
  proxy, RBAC, [rules that read the arguments](features/argument-aware-policy.md), ledger, tamper
  evidence, [the durable Postgres ledger](features/durable-ledger.md),
  [export, retention and key rotation](features/ledger-operations.md),
  [risk scoring](features/risk-scoring.md), config-driven servers, HTTP transport, OIDC identity,
  container, observability.
- **`runbooks/`** — [connector-onboarding.md](runbooks/connector-onboarding.md): govern a credentialed
  third-party MCP server with config and `.env` only.
- **`internal/`** — the product spine with its decision records and build log
  ([PRODUCT.md](internal/PRODUCT.md)), and the record of the first live Azure run. Written for the
  people building GateKeeper, not for users.

The codebase map is [STRUCTURE.md](../STRUCTURE.md) at the repo root.
