"""A tiny stand-in for an AI assistant: one governed tool call through the real gateway.

    python -m scripts.agent list                          # what tools the assistant would see
    python -m scripts.agent read_file path=welcome.txt    # a read
    python -m scripts.agent write_file path=notes.txt content="hello"   # a write (held)

It connects to ``gatekeeper serve`` over stdio exactly the way Claude Desktop or an IDE does, so
what it prints is what an assistant would get back. Use it to walk the story in
docs/WALKTHROUGH.md without a host, or to test a new server you have just governed.

Arguments are ``name=value`` pairs; a value that parses as JSON (numbers, true/false, quoted
strings, lists) is passed as that type, anything else as a string.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client


def _parse(args: list[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for arg in args:
        key, sep, raw = arg.partition("=")
        if not sep:
            raise SystemExit(f"expected name=value, got {arg!r}")
        try:
            out[key] = json.loads(raw)
        except json.JSONDecodeError:
            out[key] = raw
    return out


def _gateway_params() -> StdioServerParameters:
    config_dir = os.environ.get("GATEKEEPER_CONFIG_DIR") or str(Path("config").resolve())
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "gatekeeper.cli.app", "serve"],
        env={**os.environ, "GATEKEEPER_CONFIG_DIR": config_dir},
    )


def _text(result: types.CallToolResult) -> str:
    return "\n".join(b.text for b in result.content if isinstance(b, types.TextContent)).strip()


async def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    tool, arguments = argv[0], _parse(argv[1:])
    async with stdio_client(_gateway_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if tool == "list":
                tools = await session.list_tools()
                for t in tools.tools:
                    first_line = (t.description or "").strip().splitlines()
                    print(f"  {t.name:<20} {first_line[0] if first_line else ''}")
                return 0
            print(f"assistant -> {tool} {json.dumps(arguments)}")
            result = await session.call_tool(tool, arguments)
            label = "gateway   <- ERROR" if result.isError else "gateway   <- OK"
            print(f"{label}: {_text(result) or '(empty)'}")
            return 1 if result.isError else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
