"""Transport layer: speak MCP to the agent (stdio + HTTP via the official MCP SDK).

Thin protocol I/O only — it parses/serializes MCP and hands each tool call to the gateway
pipeline. NO authn/authz/audit logic lives here.
"""
