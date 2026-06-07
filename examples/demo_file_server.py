"""A tiny example MCP server with read + write tools, used to demo governance end-to-end.

Referenced by ``config/upstreams.yaml`` (name: demo-files). Implemented in /build using the
official MCP SDK; it intentionally exposes a destructive ``delete_file`` so the M2 approval
flow has something real to gate. This is a GOVERNED target, not part of the gateway itself.
"""

# Implemented in /build.
