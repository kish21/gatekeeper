"""The company demo: one assistant, five company systems, every action through the guard.

    gatekeeper ui                          # terminal 1: open http://127.0.0.1:8770/ui
    python -m scripts.demo_company         # terminal 2: the assistant's morning, narrated

The script plays an assistant working a support request across mail, Jira, the customer
database, SharePoint and GitHub, through a REAL ``gatekeeper serve`` over stdio (launched here
the way an MCP host launches it). Reads pass. Each write stops and waits for the presenter to
decide it in the browser; the assistant then reports what it was told. Nothing is mocked in the
governance path: the servers are demo twins with the same tool names as the real ones.

``--auto`` decides the writes itself through the UI's own API (the scripted deny/approve pattern
below), for rehearsals and screenshots. ``--ui`` points at a desk on another port.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from rich.console import Console
from rich.panel import Panel

console = Console()

#: (system, tool, arguments, narration, auto decision or None for reads)
BEATS: list[tuple[str, str, dict[str, Any], str, tuple[str, str] | None]] = [
    (
        "mail",
        "search_emails",
        {"query": "address"},
        "A customer emailed overnight. The assistant looks for it.",
        None,
    ),
    (
        "mail",
        "read_email",
        {"message_id": "M-501"},
        "It reads the message: Amara has moved and wants her address updated.",
        None,
    ),
    (
        "database",
        "query",
        {"sql": "select id, name, email, tier from customers where id = 4471"},
        "It looks her up in the customer database.",
        None,
    ),
    (
        "database",
        "execute",
        {"sql": "update customers set email = 'amara.osei@newmail.example' where id = 4471"},
        "It tries to change the record straight away. That is a write to production data.",
        ("denied", "verify the customer's identity first; open a ticket"),
    ),
    (
        "jira",
        "createJiraIssue",
        {
            "project": "OPS",
            "summary": "Customer 4471: address change request (verify identity)",
            "description": "From email M-501. Verify identity before updating the record.",
        },
        "Told no, it opens a ticket instead, so the change is tracked.",
        ("approved", ""),
    ),
    (
        "sharepoint",
        "search_documents",
        {"query": "contract"},
        "Meanwhile a colleague asks for the Contoso contract. The assistant finds it.",
        None,
    ),
    (
        "sharepoint",
        "share_document",
        {"doc_id": "DOC-1002", "with_email": "sam@contoso-partners.example"},
        "It tries to share the contract with an outside address. Data would leave the company.",
        ("denied", "external sharing of legal documents needs Legal's sign-off"),
    ),
    (
        "github",
        "list_issues",
        {},
        "An engineer asks what is open in the payments repository.",
        None,
    ),
    (
        "github",
        "merge_pull_request",
        {"number": 17},
        "It tries to merge the open pull request. That changes production code.",
        ("approved", "reviewed by the payments team this morning"),
    ),
    (
        "mail",
        "send_email",
        {
            "to": "amara@example.com",
            "subject": "Your address change",
            "body": "Thanks Amara. We have opened a ticket and will confirm once verified.",
        },
        "Finally it replies to Amara. An email cannot be un-sent.",
        ("approved", ""),
    ),
]


def _gateway_params() -> StdioServerParameters:
    config_dir = os.environ.get("GATEKEEPER_CONFIG_DIR") or str(Path("config").resolve())
    env = {**os.environ, "GATEKEEPER_CONFIG_DIR": config_dir}
    # A presenter needs longer than the default 90 s to talk and click.
    env.setdefault("GATEKEEPER_APPROVAL_TIMEOUT_S", "600")
    return StdioServerParameters(
        command=sys.executable, args=["-m", "gatekeeper.cli.app", "serve"], env=env
    )


def _text(result: types.CallToolResult) -> str:
    return "\n".join(b.text for b in result.content if isinstance(b, types.TextContent)).strip()


async def _auto_decide(ui: str, decision: tuple[str, str]) -> None:
    """Rehearsal mode: wait for the request to appear on the desk, then decide it via the API."""
    status, note = decision
    async with httpx.AsyncClient(timeout=10) as http:
        for _ in range(100):
            pending = (await http.get(f"{ui}/ui/api/pending")).json()
            if pending:
                rid = pending[-1]["id"]
                await http.post(
                    f"{ui}/ui/api/pending/{rid}/decision",
                    json={"status": status, "by": "priya", "note": note},
                )
                return
            await asyncio.sleep(0.2)
    raise SystemExit("the request never appeared on the desk (is `gatekeeper ui` running?)")


async def run(ui: str, auto: bool) -> int:
    console.print(
        Panel.fit(
            "[bold]The assistant's morning at Northwind[/]\n"
            "[dim]Mail, Jira, the customer database, SharePoint, GitHub. Every action below goes\n"
            "through GateKeeper. Reads pass. Each write waits for a person at the desk.[/]",
            border_style="cyan",
        )
    )
    mode = "(deciding automatically)" if auto else "(decide each write there)"
    console.print(f"Desk: [bold]{ui}/ui[/]   {mode}\n")
    async with stdio_client(_gateway_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for n, (system, tool, args, story, decision) in enumerate(BEATS, 1):
                console.rule(f"[dim]{n}/{len(BEATS)} · {system}")
                console.print(story)
                console.print(f"  assistant -> [bold]{tool}[/] {json.dumps(args)}")
                if decision is not None:
                    console.print("  [yellow]held for a decision at the desk...[/]")
                    if auto:
                        asyncio.get_running_loop().create_task(_auto_decide(ui, decision))
                result = await session.call_tool(tool, args)
                body = _text(result) or "(empty)"
                if result.isError:
                    console.print(f"  gateway   <- [red]{body}[/]")
                else:
                    first = body.splitlines()[0] if body else ""
                    more = f" [dim](+{len(body.splitlines()) - 1} lines)[/]" if "\n" in body else ""
                    console.print(f"  gateway   <- [green]{first}[/]{more}")
                await asyncio.sleep(0.4)
    console.rule("[dim]done")
    console.print(
        "Every call above is in the ledger. Open [bold]Activity[/] for the story of each one and "
        "[bold]Trust[/] to prove nothing was altered. `gatekeeper verify` says the same from a "
        "terminal."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ui", default="http://127.0.0.1:8770", help="where `gatekeeper ui` is")
    parser.add_argument("--auto", action="store_true", help="decide writes automatically")
    args = parser.parse_args()
    return asyncio.run(run(args.ui.rstrip("/"), args.auto))


if __name__ == "__main__":
    raise SystemExit(main())
