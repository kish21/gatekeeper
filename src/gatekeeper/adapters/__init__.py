"""Adapters — concrete, swappable implementations of ``ports/``, selected via config.

Planned sub-packages (one folder per port):
    identity/   static_token.py (M1 stub)         | oidc.py (deferred)
    policy/     cedar.py
    ledger/     sqlite.py + hashchain.py (keyed-HMAC chain)
    upstream/   mcp_client.py (MCP client to a real server)
    llm/        claude.py + stub.py (M2)
This is the ONLY layer allowed to import an external SDK.
"""
