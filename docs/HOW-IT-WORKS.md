# How GateKeeperAI works — a plain-English guide

*Written for a non-technical reader: a founder, seller, or buyer who needs to understand what this
does and how a customer would use it — without reading code. A diagram version of this page lives in
[`how-it-works.svg`](how-it-works.svg) (open it in any web browser to show on a call).*

---

## In one line

**GateKeeperAI is a security guard that sits between your AI assistant and the tools it uses.**

Every time the AI tries to *do* something — read a file, create a GitHub issue, send a message —
the guard checks who's asking, checks the rulebook, writes it in a tamper-proof logbook, and only
then lets it through (or blocks it).

---

## The mental model: a guard at reception

Picture an office building with a **guard at the front desk**:

```
   AI assistant              THE GUARD                         The tools
   ("the agent")             (GateKeeperAI)                    (MCP servers)
   ┌───────────┐             ┌────────────────────────┐        ┌──────────────┐
   │           │  shows its  │ 1. check the badge      │        │  files       │
   │   🤖      │ ──badge──▶  │ 2. check the rulebook   │ ──▶    │  GitHub      │
   │           │  (a token)  │ 3. write the logbook    │  let   │  the clock   │
   │           │             │ 4. open the door — or   │  in    │  ...anything │
   └───────────┘             │    refuse (blocked)     │        └──────────────┘
                             └────────────────────────┘
                                  every action, checked + recorded
```

- **The agent** = the AI assistant (for example Claude Desktop, or a custom AI app your company
  builds). It's the thing that *wants to use tools*.
- **The badge** = a *token* the agent carries. The badge says **who** the agent is and **what level
  of access** it has.
- **The tools** = the outside systems the AI connects to (a file store, GitHub, a database…). In the
  standard these are called **MCP servers**. Think of each as a *room* in the building.
- **The guard** = GateKeeperAI. For every single action it does four things: checks the badge
  (*identity*), checks the rulebook (*policy*), writes it in a tamper-proof logbook (*audit*), then
  forwards the action — or blocks it.

---

## Who is "the agent"? (and who are alice and bob?)

This is the part the demo makes confusing, so let's be precise.

- **`alice` and `bob` are NOT agents. They are badges** — identities with a role:
  - `alice` carries an **operator** badge → may read **and** write.
  - `bob` carries a **read-only** badge → may read, but **never** write.
  - `root` carries an **admin** badge → full access.
- **The agent is whoever is holding the badge.** A real AI assistant connects while carrying, say,
  alice's badge — and from then on every action it takes is checked and logged *as alice*.

### So why does the demo feel "hardcoded"?

Because in the demo, **the demo program itself is pretending to be the agent.** It picks up alice's
badge and reads a file (allowed), then picks up bob's badge and tries to write (blocked). It's a
**scripted tour** — it does the same thing every time so you can show it reliably.

In real life, a **real AI assistant** holds the badge and decides its *own* actions. The guard
underneath behaves identically. The only thing that's scripted is the demo's *tour*, not the guard.

---

## Is everything hardcoded? No — it's almost all plain config

The important decisions do **not** live in the program's code. They live in **plain text settings
files** anyone can open and edit:

| What you control | Where it lives | In the code? |
|---|---|---|
| Which tools/servers are governed | `config/upstreams.yaml` | ❌ No — plain settings |
| Who is allowed to do what (the rulebook) | `policies/gatekeeper.cedar` | ❌ No — plain settings |
| The badges (who maps to which role) | `config/identities.yaml` | ❌ No — plain settings |
| Which actions count as "writes" | `config/product.yaml` | ❌ No — plain settings |

The **only** scripted thing is the demo's tour (`scripts/demo.py`). The guard engine it drives is
fully settings-driven. **Proof:** the *clock* server in the demo is a real, third-party tool that the
GateKeeper team did **not** build — and it's fully governed just by adding it to the settings file.
Zero code.

---

## How a customer uses it in their company

GateKeeperAI runs as a small program **on the same machine as the AI assistant** — quietly, in the
middle. A customer sets it up once:

1. **Install** GateKeeperAI on the machine where their AI assistant runs.
2. **Edit the settings files** — list the tools/servers they want governed, set the badges
   (who/which role), and keep or adjust the rulebook.
3. **Add two secrets** to a private `.env` file: a key that makes the logbook tamper-proof, and the
   badge token the AI will carry.
4. **Run one setup command** (creates the logbook), then **start GateKeeperAI**.
5. **Point the AI assistant at GateKeeperAI** instead of directly at the tools.

From that moment on, **every action the AI takes is checked and recorded** — with no change to the
AI assistant itself, and no change to the tools.

They can check the result anytime:
- *"Show me everything the AI did"* → the logbook (`tail`).
- *"Prove nobody tampered with the records"* → the integrity check (`verify`).

---

## Adding a new tool — for example, a GitHub server

The promise is **"govern any tool by settings, zero code."** To bring a GitHub server under the
guard, a customer adds a short block to `config/upstreams.yaml`:

```yaml
  - name: github
    transport: stdio
    command: ["npx", "-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: { from_env: GITHUB_TOKEN }   # the password — see below
    reads:  ["search_repositories", "get_file", "list_issues"]   # actions that only look
    writes: ["create_issue", "merge_pull_request", "delete_branch"]  # actions that change things
```

That's it — **no code, and no rulebook change needed.** The existing rules are *role-based*, so they
already apply to the new tools automatically:
- A **read-only** badge calling `create_issue` (a write) → **blocked**.
- An **operator** badge calling `create_issue` → **allowed** (and recorded).

### How the GitHub password is handled (securely)

The GitHub server needs a **password** (an access token) to talk to GitHub. GateKeeperAI keeps that
password **out of the settings file** — you reference it by *name* with `{ from_env: GITHUB_TOKEN }`,
and put the actual value in the private `.env` file:

```
# in .env (never shared, never in the settings file)
GITHUB_TOKEN=ghp_your_real_token_here
```

At start-up the guard reads the value from `.env` (or from the deployment's environment in
production) and hands it to the GitHub server. If you reference a password that isn't set, the guard
**refuses to start** with a clear message — so a half-configured credential can never slip through.
The password is never written to the logbook or the logs.

---

## What works today vs. what's coming

Be precise with customers — don't oversell:

| Capability | Status |
|---|---|
| Every action authenticated (badge checked) | ✅ Works today |
| Role-based allow/deny rules (read-only blocked from writing) | ✅ Works today |
| Tamper-proof, verifiable logbook of every action | ✅ Works today |
| Govern any tool by settings, zero code | ✅ Works today |
| One bad/offline tool doesn't take the guard down | ✅ Works today |
| Securely give a tool its password from `.env` (e.g. a GitHub token) | ✅ Works today |
| Run **over the network** so a whole team shares one gateway (not one laptop) | ✅ Works today (HTTPS added by Azure when you deploy — guide ready) |
| **Enterprise login** (OIDC — Entra ID / Okta / Google) instead of static badges | ✅ Works today (plug in your tenant by config) |
| **Live health metrics + tamper / deny alerts** | ✅ Works today |
| **A human approves risky writes before they happen** | 🔜 Coming (next milestone) |
| **AI risk-scores each action to decide what needs approval** | 🔜 Coming (next milestone) |

> Today, an **operator's** writes go straight through (and are fully logged). The *human-approval
> step* for risky writes is the **next milestone** — so don't claim "every write needs sign-off"
> yet. A **read-only** badge is already blocked from writing, today.

> **Showing the enterprise version?** The hosted story — HTTPS, your real corporate login, and Azure —
> has its own plain-English guide with a "what to show on a call" demo script:
> [SHOWCASE-AZURE.md](SHOWCASE-AZURE.md).

---

## Mini-glossary

- **Agent** — the AI assistant that wants to use tools (e.g. Claude Desktop, or your own AI app).
- **MCP server** — a tool the AI connects to (files, GitHub, a database…). "MCP" is just the
  standard way AIs plug into tools.
- **Token (badge)** — a secret string the agent carries that proves who it is.
- **Role** — the access level on a badge: read-only, operator, or admin.
- **Policy (rulebook)** — the settings that say which role may do what. Written in *Cedar*, a
  purpose-built rules language that can be checked for correctness.
- **Audit ledger (logbook)** — the tamper-proof record of every action, with a built-in way to
  *prove* it was never altered.

---

*The deepest "why" behind these choices — the vision, scope, and the architecture decisions — lives
in [`../PRODUCT.md`](../PRODUCT.md). This page is the plain-English version for a non-technical
audience.*
