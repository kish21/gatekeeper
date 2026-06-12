"""A tiny example MCP server with read + write tools, used to demo governance end-to-end.

Referenced by ``config/upstreams.yaml`` (name: demo-files). Built on the official MCP SDK
(``FastMCP``); it intentionally exposes a destructive ``delete_file`` so the M2 approval flow has
something real to gate. This is a GOVERNED TARGET, not part of the gateway itself.

All file access is confined to a sandbox root (``$DEMO_FILE_ROOT``, default
``./.gatekeeper/demo_sandbox``) and path-traversal is rejected — a server GateKeeper governs should
still be safe on its own.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo-files")

# FastMCP's constructor runs ``logging.basicConfig(INFO)``, which makes the low-level MCP server
# log a "Processing request of type …" line per call to stderr. That is internal protocol chatter,
# not something a demo audience (or the test output) needs — quiet it so the governance story is the
# only thing on screen. Behaviour is unchanged; only this server's request-logging verbosity drops.
logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)

#: Env var naming the sandbox root (no hardcoded absolute path).
_ROOT_ENV = "DEMO_FILE_ROOT"
_DEFAULT_ROOT = "./.gatekeeper/demo_sandbox"


def _root() -> Path:
    root = Path(os.environ.get(_ROOT_ENV, _DEFAULT_ROOT)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe(path: str) -> Path:
    """Resolve ``path`` inside the sandbox root, rejecting traversal (``..``/absolute escapes)."""
    root = _root()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"path {path!r} escapes the sandbox root")
    return candidate


@mcp.tool()
def read_file(path: str) -> str:
    """Read a UTF-8 text file from the demo sandbox."""
    return _safe(path).read_text(encoding="utf-8")


@mcp.tool()
def list_dir(path: str = ".") -> list[str]:
    """List entry names in a sandbox directory."""
    return sorted(child.name for child in _safe(path).iterdir())


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Write (create/overwrite) a UTF-8 text file in the sandbox. A MUTATION."""
    target = _safe(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} bytes to {path}"


@mcp.tool()
def delete_file(path: str) -> str:
    """Delete a file in the sandbox. A DESTRUCTIVE MUTATION (the M2 approval target)."""
    _safe(path).unlink()
    return f"deleted {path}"


if __name__ == "__main__":
    mcp.run()
