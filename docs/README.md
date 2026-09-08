# docs/

Start with whichever of these matches you:

- **New to GateKeeper?** [USE-CASE-STORY.md](USE-CASE-STORY.md) tells the use case as a story, then
  [HOW-IT-WORKS.md](HOW-IT-WORKS.md) explains the parts in plain English.
- **Want to run it?** [getting-started.md](getting-started.md): install, `init`, `doctor`, connect your
  MCP host, read the audit trail.
- **Deploying for a team?** [deploy/azure-container-apps.md](deploy/azure-container-apps.md), one command
  on Azure, with an honest section on what is not durable yet. [SHOWCASE-AZURE.md](SHOWCASE-AZURE.md)
  is the plain-English hosted story plus a demo script for a customer call.
- **A word you do not know?** [glossary.md](glossary.md).

Reference:

- **`features/`** — one page per built capability (what it does, how it is configured, its limits):
  proxy, RBAC, ledger, tamper evidence, config-driven servers, HTTP transport, OIDC identity, container,
  observability.
- **`runbooks/`** — [connector-onboarding.md](runbooks/connector-onboarding.md): govern a credentialed
  third-party MCP server with config and `.env` only.
- **`internal/`** — the product spine with its decision records and build log
  ([PRODUCT.md](internal/PRODUCT.md)), and the record of the first live Azure run. Written for the
  people building GateKeeper, not for users.

The codebase map is [STRUCTURE.md](../STRUCTURE.md) at the repo root.
