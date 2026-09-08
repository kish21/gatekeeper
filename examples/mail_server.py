"""A demo twin of a mailbox MCP server (Outlook / Gmail shape): search, read, send.

Sending is the write that matters: once an email has left, it cannot be un-sent. Backed by an
in-memory inbox; ``send_email`` records to an outbox instead of delivering anything.
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mail")
logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)

_INBOX: dict[str, dict[str, str]] = {
    "M-501": {
        "from": "amara@example.com",
        "subject": "Please update my address",
        "body": "Hi, I have moved. New address: 12 Harbour Road, Leith. Can you update it? Amara",
    },
    "M-502": {
        "from": "billing@contoso.example",
        "subject": "Invoice 2026-0912 overdue",
        "body": "Payment for invoice 2026-0912 (EUR 18,400) is 14 days overdue.",
    },
    "M-503": {
        "from": "it-security@northwind.example",
        "subject": "Reminder: quarterly access review",
        "body": "Managers: confirm your team's access by Friday.",
    },
}
_OUTBOX: list[dict[str, str]] = []


@mcp.tool()
def search_emails(query: str) -> str:
    """Search the inbox by sender, subject, or body."""
    q = query.lower()
    hits = [
        f"{i}  {m['from']:<28} {m['subject']}"
        for i, m in _INBOX.items()
        if q in m["from"].lower() or q in m["subject"].lower() or q in m["body"].lower()
    ]
    return "\n".join(hits) or "no messages match"


@mcp.tool()
def read_email(message_id: str) -> str:
    """Read one message."""
    try:
        m = _INBOX[message_id]
    except KeyError:
        raise ValueError(f"no message {message_id}") from None
    return f"From: {m['from']}\nSubject: {m['subject']}\n\n{m['body']}"


@mcp.tool()
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email. A MUTATION that cannot be undone once it leaves."""
    _OUTBOX.append({"to": to, "subject": subject, "body": body})
    return f"sent to {to}: {subject}"


if __name__ == "__main__":
    mcp.run()
