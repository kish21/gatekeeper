"""A demo twin of a SharePoint document server, for showing governance without a tenant.

Same shape as a real SharePoint / Microsoft Graph MCP server (search, get, update, delete,
share), backed by a few in-memory documents. Swap it for the real server in
``config/upstreams.yaml`` when you have a tenant; the gateway does not care which one it is.
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sharepoint")
logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)

_DOCS: dict[str, dict[str, str]] = {
    "DOC-1001": {
        "title": "Q3 Board Pack.docx",
        "library": "Finance",
        "owner": "cfo@northwind.example",
        "content": "Q3 revenue 4.2M, up 11%. Headcount 212. Cash runway 19 months.",
    },
    "DOC-1002": {
        "title": "Supplier Contract - Contoso.pdf",
        "library": "Legal",
        "owner": "legal@northwind.example",
        "content": "Master services agreement, term 24 months, notice period 90 days.",
    },
    "DOC-1003": {
        "title": "Holiday Policy 2026.docx",
        "library": "HR",
        "owner": "hr@northwind.example",
        "content": "25 days annual leave; carry-over of 5 days; requests via the HR portal.",
    },
}


def _doc(doc_id: str) -> dict[str, str]:
    try:
        return _DOCS[doc_id]
    except KeyError:
        raise ValueError(f"no document {doc_id}") from None


@mcp.tool()
def search_documents(query: str) -> str:
    """Search document titles and contents. Returns id, title and library per hit."""
    q = query.lower()
    hits = [
        f"{i}  {d['title']}  ({d['library']})"
        for i, d in _DOCS.items()
        if q in d["title"].lower() or q in d["content"].lower()
    ]
    return "\n".join(hits) if hits else "no documents match"


@mcp.tool()
def get_document(doc_id: str) -> str:
    """Read a document's content."""
    d = _doc(doc_id)
    return f"{d['title']} [{d['library']}, owner {d['owner']}]\n\n{d['content']}"


@mcp.tool()
def update_document(doc_id: str, content: str) -> str:
    """Replace a document's content. A MUTATION."""
    _doc(doc_id)["content"] = content
    return f"updated {doc_id} ({len(content)} chars)"


@mcp.tool()
def delete_document(doc_id: str) -> str:
    """Delete a document. A DESTRUCTIVE MUTATION."""
    title = _doc(doc_id)["title"]
    del _DOCS[doc_id]
    return f"deleted {doc_id} ({title})"


@mcp.tool()
def share_document(doc_id: str, with_email: str) -> str:
    """Share a document with an external address. A MUTATION (data leaves the company)."""
    title = _doc(doc_id)["title"]
    return f"shared {title} with {with_email}"


if __name__ == "__main__":
    mcp.run()
