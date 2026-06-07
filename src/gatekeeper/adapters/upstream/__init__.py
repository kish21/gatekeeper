"""Upstream adapters (implement ports.UpstreamClient), selected via config adapters.upstream.

mcp_client.py — an MCP *client* that forwards a governed call to a real upstream MCP server
                (stdio/HTTP) and returns its result. Timeout/retry/breaker per ADR-004.
"""
