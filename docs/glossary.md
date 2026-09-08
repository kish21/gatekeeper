# Glossary

The words the docs use, and what they mean here. Where two names were used for one thing, the
first one is the one we keep.

| Term | Meaning |
|---|---|
| **Agent** | The AI assistant that wants to use tools: Claude Desktop, an IDE, or your own app |
| **MCP** | Model Context Protocol, the standard way an agent talks to a tool server |
| **MCP host** | The program that launches and talks to MCP servers on the agent's behalf (Claude Desktop is one) |
| **Tool server** (also *upstream*) | A server the gateway governs: files, GitHub, a database. Listed in `config/upstreams.yaml` |
| **Tool** | One action a tool server offers, such as `read_file` or `create_issue` |
| **Gateway** | GateKeeper itself: the MCP server the agent connects to, which checks and forwards every call |
| **Token** (also *badge*, *bearer token*) | The secret string a caller presents. It resolves to a principal and a role |
| **Principal** | Who a call is attributed to, such as `alice`, or a corporate user id under OIDC |
| **Role** | The access level of a principal: `readonly`, `operator`, or `admin` |
| **Policy** (also *rulebook*) | The rules that say which role may call which tool. Written in Cedar, in `policies/*.cedar` |
| **Cedar** | A small, analyzable policy language. The gateway denies anything no rule permits |
| **Read / write** | The kind of a call. Declared per server in `upstreams.yaml`, or guessed from the tool name |
| **Ledger** (also *audit ledger*, *logbook*) | The append-only record of every decision and outcome |
| **Hash chain** | Each ledger entry carries a keyed hash of itself plus the previous entry's hash, so changing, inserting, or removing an entry breaks the chain |
| **HMAC key** | The secret that keys the hash chain (`GATEKEEPER_HMAC_KEY`). Without it a forger cannot recompute a valid chain |
| **Head** | The newest entry's hash. Pin it out of band and `verify --expect-head` also detects entries removed from the end |
| **Verify** | `gatekeeper verify`: walks the chain and reports intact, or the exact record where it broke |
| **Fail-closed** | On any error in identity, policy, or ledger writing, the call is denied, never allowed |
| **Audit before act** | The decision is written to the ledger before the call is forwarded |
| **stdio** | The gateway running as a subprocess of the MCP host, one identity per process |
| **HTTP transport** | The gateway running as a network service; each request carries its own token |
| **OIDC** | OpenID Connect: corporate login. Tokens are validated against the identity provider's public keys and a group is mapped to a role |
| **Allowed hosts** | Hostnames the HTTP transport accepts, a defense against DNS rebinding. Set automatically on Azure |
| **Placeholder tokens** | The `...-REPLACE-ME` tokens in `config/identities.yaml`. Public knowledge; refused on a network-reachable bind |
