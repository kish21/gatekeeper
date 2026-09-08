# Getting started

This page takes you from a fresh checkout to a gateway that your MCP host launches, and explains
the few files you will ever touch. Ten minutes.

## 1. Install

```bash
git clone https://github.com/kish21/gatekeeper && cd gatekeeper
make install
```

`make install` uses `uv` if you have it and falls back to `pip`. Either way it installs the gateway,
the demo servers, and the developer tools into `.venv`. Activate it (`source .venv/bin/activate`,
or `.venv\Scripts\activate` on Windows) so the `gatekeeper` command is on your path. `make demo`
works without activation.

## 2. Watch it work

```bash
make demo
```

Five beats: an allowed read, a denied write, a third-party server governed by config, the ledger
verified clean, and a deliberate tamper caught. It never touches your real settings or ledger.

## 3. Set it up

```bash
gatekeeper init
```

This does the things you used to do by hand:

- generates a strong key for the ledger's hash chain and writes it to `.env`
- writes the demo operator token to `.env` so the stdio gateway knows who is calling
- creates the audit ledger, running the schema migration
- seeds the demo file server's sandbox with a sample file

It never overwrites a value you already set, so it is safe to run again.

## 4. Check it and connect your host

```bash
gatekeeper doctor
```

`doctor` checks the key, the ledger, the policy, the agent token, and whether each governed server
can actually be launched. Every row is OK or FAIL with a reason. It then prints the block to paste
into your MCP host, with absolute paths:

```json
{
  "mcpServers": {
    "gatekeeper": {
      "command": "/abs/path/gatekeeper/.venv/bin/gatekeeper",
      "args": ["serve"],
      "env": { "GATEKEEPER_CONFIG_DIR": "/abs/path/gatekeeper/config" }
    }
  }
}
```

- **Claude Desktop:** add it to `claude_desktop_config.json` and restart the app.
- **Other hosts:** the same three fields, in that host's MCP servers setting.

The host launches `gatekeeper serve` for you. You do not run it by hand for normal use. The
secrets stay in `.env` next to the config folder, so nothing sensitive goes into the host config.

## 5. Approve or deny writes

Reads go straight through. A write from an operator is held until someone decides. The easiest
place to decide is the desk:

```bash
gatekeeper ui                              # then open http://127.0.0.1:8770/ui
```

It shows the writes waiting (who, which tool, what would change), the activity so far, a
one-click integrity check, and the governed servers. It runs next to a gateway your MCP host
launched; both share the ledger. The same decisions are available from a terminal:

```bash
gatekeeper pending                         # who wants to change what
gatekeeper approve <id>                    # recorded under your name, then carried out
gatekeeper deny <id> --reason "not yet"    # recorded, never carried out
```

No decision within the timeout (90 seconds by default, `approval.timeout_s` in
`config/product.yaml`) counts as a deny. Roles listed under `exempt_roles` (admin by default)
write without waiting. Set `approval.writes: off` to disable holding altogether.

Without an assistant installed, `python -m scripts.agent write_file path=notes.txt content=hi`
makes a write through the real gateway so you can practise the approval flow from two
terminals. [One afternoon with GateKeeper](WALKTHROUGH.md) shows the whole exchange.

## 6. Look at the audit trail

```bash
gatekeeper tail --with-id     # the most recent calls, with each call's id
gatekeeper show <id>          # one call: who, what, each decision, outcome; a prefix is enough
gatekeeper verify             # walks the whole chain; exit 0 means untampered
gatekeeper stats              # allow and deny counts, busiest tools
```

`verify` prints a head hash. Keep it somewhere the ledger's machine cannot reach (a ticket, a
separate log). Next time, run `gatekeeper verify --expect-head <hash>` and a chain that has had
records removed from its end is reported too.

## The files you might edit

| File | What it controls |
|---|---|
| `config/upstreams.yaml` | Which servers are governed, how to launch them, which of their tools are reads and which are writes. Ships with demo twins of SharePoint, Jira, GitHub, a database and a mailbox |
| `config/identities.yaml` | The demo tokens and their roles. Replace them with your own for any real use |
| `policies/gatekeeper.cedar` | The rulebook: read-only may read, operator and admin may read and write. Deny by default |
| `config/platform.yaml` | How the gateway runs: transport, identity adapter, ledger path. Every value has an environment variable next to it |
| `.env` | Secrets and overrides. Created by `init`; never committed |

`config/product.yaml` holds the approval rule (which writes wait, for how long, which roles are
exempt) and how a tool name is guessed to be a write when a server has no annotation. You will not
normally touch anything under `src/`.

## Governing a server that needs a credential

Reference the secret by name in `upstreams.yaml` and put the value in `.env`:

```yaml
  - name: github
    transport: stdio
    command: ["npx", "-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: { from_env: GITHUB_TOKEN }
    reads:  ["search_repositories", "get_file_contents", "list_issues"]
    writes: ["create_issue", "merge_pull_request", "delete_branch"]
```

If `GITHUB_TOKEN` is not set the gateway refuses to start and says so. The server receives that
one variable plus what it needs to launch, nothing else from the gateway's environment. The
[connector onboarding runbook](runbooks/connector-onboarding.md) has a fuller template.

## When something is wrong

Run `gatekeeper doctor` first. The common cases:

- **HMAC key FAIL:** run `gatekeeper init`.
- **agent token FAIL:** `GATEKEEPER_AGENT_TOKEN` in `.env` must be one of the tokens in `config/identities.yaml`.
- **server FAIL, not on PATH:** the launcher in `upstreams.yaml` is not installed. For the `time`
  demo server, `pip install -e ".[demo]"`.
- **The host says the server disconnected:** check the host's log for the gateway's stderr. The
  gateway prints the exact problem there, never on stdout.

## Running it over HTTP for a team

Set two variables and start it:

```bash
GATEKEEPER_TRANSPORT=http gatekeeper serve      # loopback only, http://127.0.0.1:8765/mcp
```

Binding beyond the local machine requires `GATEKEEPER_HTTP_ALLOW_NON_LOOPBACK=1`, TLS in front
of it, and either your own tokens (`GATEKEEPER_IDENTITIES`) or OIDC (`GATEKEEPER_IDENTITY=oidc`).
The gateway refuses to expose the demo tokens on a public interface. The full hosted path is in
[Deploy to Azure](deploy/azure-container-apps.md).
