# GateKeeperAI

**A security guard between your AI agent and the tools it uses.** Every tool call is checked for
who is asking, checked against a rulebook, written to a tamper-evident audit trail, and only then
let through. It works with any server that speaks the Model Context Protocol (MCP), and you add a
server by editing a settings file, not by writing code.

## Why you would want this

When an AI assistant can read files, open tickets, or change records, three questions come up fast:

| Question | Without GateKeeper | With GateKeeper |
|---|---|---|
| Who is the AI acting as? | A shared password nobody can trace | Every call carries an identity and a role, recorded on every line |
| What is it allowed to do? | Whatever it can be talked into | A readable rulebook, and a write waits until a named human says yes |
| What did it actually do? | A log file anyone could edit | A hash-chained ledger you can *prove* was never altered |

The last row is the point. You do not have to trust the gateway. You can check it.

**Five minutes, pasted from a real run:** [One afternoon with GateKeeper](docs/WALKTHROUGH.md)
shows an assistant's write being held, denied by a person with a reason, approved on the second
try, and the whole record verified.

## See it in one command

```bash
make install && make demo
```

Nothing to configure. It uses a throwaway ledger in a temp folder and cleans up after itself.
This is the real thing, cut down to the lines that matter:

```text
Beat 1/5 - Transparent
  ALLOW  alice (operator)   demo-files:read_file
           relayed from the real server -> "Hello from GateKeeperAI ..."

Beat 2/5 - RBAC bites
  DENY   bob (read-only)    demo-files:write_file
           policy: denied by cedar policy: role 'readonly' may not write demo-files::write_file
           sandbox now contains -> welcome.txt  (secret.txt was never created - deny had no effect)

Beat 3/5 - Tool-agnostic
  ALLOW  alice (operator)   time:get_current_time
           relayed from a server we did NOT write -> {"timezone": "UTC", "datetime": ...}

Beat 4/5 - Provable audit
| seq | principal | role     | tool                  | action | verdict |
| 1   | alice     | operator | demo-files:read_file  | read   | allow   |
| 3   | bob       | readonly | demo-files:write_file | write  | deny    |
| 6   | alice     | operator | time:get_current_time | read   | allow   |
  verify -> OK  chain intact, 7 entries verified

Beat 5/5 - Don't trust - verify
  tampering with seq=3: rewriting its 'reason' to look benign...
  verify -> TAMPERED  broken at seq=3: entry_hash mismatch (record altered or wrong key)
```

## Use it for real

Three commands take a fresh checkout to a gateway your MCP host can launch:

```bash
gatekeeper init      # generates the secrets into .env, creates the ledger, seeds the demo files
gatekeeper doctor    # checks everything, then prints the block to paste into your MCP host
```

`doctor` prints something like this. Paste it into Claude Desktop's `claude_desktop_config.json`
(or any host's `mcpServers` block). The paths are absolute, so it works from anywhere:

```json
{
  "mcpServers": {
    "gatekeeper": {
      "command": "/home/you/gatekeeper/.venv/bin/gatekeeper",
      "args": ["serve"],
      "env": { "GATEKEEPER_CONFIG_DIR": "/home/you/gatekeeper/config" }
    }
  }
}
```

From then on the host launches the gateway, the gateway launches the governed servers, and every
call goes through the guard. Reads pass. A write waits for you:

```bash
gatekeeper pending            # writes waiting for a human, with what they want to change
gatekeeper approve <id>       # recorded under your name, then carried out
gatekeeper deny <id> --reason "not yet"   # recorded, never carried out
```

Look at what happened whenever you like:

```bash
gatekeeper tail --with-id     # the audit trail
gatekeeper show <id>          # one call: who, what, each decision, the outcome
gatekeeper verify             # exit 0 = untampered; prints a head hash you can pin
```

No assistant installed yet? `python -m scripts.agent read_file path=welcome.txt` makes one call
through the real gateway the way an assistant would.

Full walkthrough, including what each file means: [Getting started](docs/getting-started.md).

## Govern your own server

Add a block to `config/upstreams.yaml`. That is the whole integration:

```yaml
  - name: github
    transport: stdio
    command: ["npx", "-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: { from_env: GITHUB_TOKEN }   # the value stays in .env, never here
    reads:  ["search_repositories", "get_file_contents", "list_issues"]
    writes: ["create_issue", "merge_pull_request", "delete_branch"]
```

The existing rulebook already applies: a read-only role calling `create_issue` is denied, an
operator is allowed, and both are recorded. Governed servers receive only the environment they
need to start plus what you declare for them, never the gateway's own secrets.

## Run it for a whole team

The same gateway runs as a container over HTTPS, with your corporate login (OIDC: Entra ID, Okta,
Google) deciding each caller's role. Everything a hosted deployment differs on is an environment
variable, so you never rebuild the image to change a hostname or switch identity providers.

```bash
az login && bash scripts/deploy_azure.sh     # Azure Container Apps, one command, safe to re-run
```

See [Deploy to Azure](docs/deploy/azure-container-apps.md), including what is and is not durable yet.

## What works today

| Capability | Status |
|---|---|
| Every call authenticated, policy-checked, recorded before it is forwarded | Works today |
| Writes held for a named human to approve or deny, with a timeout that counts as no | Works today |
| Tamper-evident ledger; `verify` pinpoints any altered, inserted, or removed record | Works today |
| Any MCP server governed by config alone, credentials referenced by name | Works today |
| HTTP transport, OIDC login, container image, `/metrics`, deny-spike alerts | Works today |
| One-command Azure deploy with fresh per-deployment tokens | Works today; the hosted ledger is not yet durable across restarts |
| AI risk-scoring so only risky writes need approval | Next milestone, not built |

## Learn more

- [One afternoon with GateKeeper](docs/WALKTHROUGH.md), the real run, and [the use case as a story](docs/USE-CASE-STORY.md)
- [How it works](docs/HOW-IT-WORKS.md) in plain English, and [GateKeeper on Azure](docs/SHOWCASE-AZURE.md)
- [Glossary](docs/glossary.md), [feature docs](docs/features/), [codebase map](STRUCTURE.md)
- Design history and decision records: [docs/internal/PRODUCT.md](docs/internal/PRODUCT.md)

Apache-2.0. See [`LICENSE`](LICENSE) and [`SECURITY.md`](SECURITY.md).
