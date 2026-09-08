"""A demo twin of the Atlassian Jira MCP server, for showing governance without a Jira site.

Tool names follow the real Atlassian server (searchJiraIssuesUsingJql, getJiraIssue,
createJiraIssue, transitionJiraIssue, addCommentToJiraIssue), backed by in-memory issues.
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("jira")
logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)

_ISSUES: dict[str, dict[str, object]] = {
    "OPS-101": {
        "summary": "Rotate the payment gateway API key",
        "status": "In Progress",
        "assignee": "marcus",
        "comments": ["Waiting on the vendor's new key."],
    },
    "OPS-102": {
        "summary": "Customer 4471 address change request",
        "status": "Open",
        "assignee": "unassigned",
        "comments": [],
    },
    "OPS-103": {
        "summary": "Quarterly access review",
        "status": "Done",
        "assignee": "priya",
        "comments": ["Completed 2026-08-30."],
    },
}
_NEXT = [104]
_STATUSES = ("Open", "In Progress", "Done", "Cancelled")


def _issue(key: str) -> dict[str, object]:
    try:
        return _ISSUES[key]
    except KeyError:
        raise ValueError(f"no issue {key}") from None


@mcp.tool()
def searchJiraIssuesUsingJql(jql: str) -> str:  # noqa: N802 — matches the real server's name
    """Search issues. Accepts a plain word or a simple `status = X` clause."""
    q = jql.strip()
    if q.lower().startswith("status"):
        wanted = q.split("=", 1)[-1].strip().strip("'\"").lower()
        hits = [k for k, i in _ISSUES.items() if str(i["status"]).lower() == wanted]
    else:
        hits = [k for k, i in _ISSUES.items() if q.lower() in str(i["summary"]).lower() or not q]
    return "\n".join(f"{k}  {_ISSUES[k]['status']:<12} {_ISSUES[k]['summary']}" for k in hits) or (
        "no issues match"
    )


@mcp.tool()
def getJiraIssue(key: str) -> str:  # noqa: N802
    """Read one issue."""
    i = _issue(key)
    comments = "\n".join(f"  - {c}" for c in i["comments"]) or "  (no comments)"
    return f"{key}: {i['summary']}\nstatus: {i['status']}  assignee: {i['assignee']}\n{comments}"


@mcp.tool()
def createJiraIssue(project: str, summary: str, description: str = "") -> str:  # noqa: N802
    """Create an issue. A MUTATION."""
    key = f"{project.upper()}-{_NEXT[0]}"
    _NEXT[0] += 1
    _ISSUES[key] = {
        "summary": summary,
        "status": "Open",
        "assignee": "unassigned",
        "comments": [description] if description else [],
    }
    return f"created {key}: {summary}"


@mcp.tool()
def transitionJiraIssue(key: str, status: str) -> str:  # noqa: N802
    """Move an issue to a new status. A MUTATION."""
    if status not in _STATUSES:
        raise ValueError(f"status must be one of {', '.join(_STATUSES)}")
    _issue(key)["status"] = status
    return f"{key} -> {status}"


@mcp.tool()
def addCommentToJiraIssue(key: str, body: str) -> str:  # noqa: N802
    """Add a comment. A MUTATION."""
    comments = _issue(key)["comments"]
    assert isinstance(comments, list)
    comments.append(body)
    return f"commented on {key}"


if __name__ == "__main__":
    mcp.run()
