"""A demo twin of the official GitHub MCP server, for showing governance without a token.

Tool names follow the real server (list_issues, get_file_contents, create_issue,
create_pull_request, merge_pull_request, delete_branch). The real server is one config block
away: see the commented entry in ``config/upstreams.yaml``.
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("github")
logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)

_REPO = "northwind/payments"
_FILES = {
    "README.md": "# payments\nHandles card and bank transfers.\n",
    "src/rates.py": "FEE_PERCENT = 1.4\nFX_SPREAD = 0.002\n",
}
_ISSUES: dict[int, dict[str, str]] = {
    41: {"title": "Refund webhook retries twice", "state": "open"},
    42: {"title": "Add EUR settlement report", "state": "open"},
}
_PRS: dict[int, dict[str, str]] = {
    17: {"title": "Raise FX spread to 0.003", "head": "fx-spread", "state": "open"},
}
_BRANCHES = {"main", "fx-spread", "release-2026-09"}


@mcp.tool()
def list_issues(repo: str = _REPO, state: str = "open") -> str:
    """List issues in the repository."""
    rows = [f"#{n}  {i['title']}" for n, i in _ISSUES.items() if i["state"] == state]
    return "\n".join(rows) or f"no {state} issues in {repo}"


@mcp.tool()
def get_file_contents(path: str, repo: str = _REPO) -> str:
    """Read a file from the default branch."""
    try:
        return _FILES[path]
    except KeyError:
        raise ValueError(f"{path} not found in {repo}") from None


@mcp.tool()
def create_issue(title: str, body: str = "", repo: str = _REPO) -> str:
    """Open an issue. A MUTATION."""
    n = max(_ISSUES) + 1
    _ISSUES[n] = {"title": title, "state": "open"}
    return f"opened {repo}#{n}: {title}"


@mcp.tool()
def create_pull_request(title: str, head: str, base: str = "main", repo: str = _REPO) -> str:
    """Open a pull request. A MUTATION."""
    n = max(_PRS) + 1
    _PRS[n] = {"title": title, "head": head, "state": "open"}
    return f"opened {repo} PR #{n}: {title} ({head} -> {base})"


@mcp.tool()
def merge_pull_request(number: int, repo: str = _REPO) -> str:
    """Merge a pull request into main. A MUTATION (changes production code)."""
    pr = _PRS.get(number)
    if pr is None or pr["state"] != "open":
        raise ValueError(f"PR #{number} is not open")
    pr["state"] = "merged"
    return f"merged {repo} PR #{number}: {pr['title']}"


@mcp.tool()
def delete_branch(branch: str, repo: str = _REPO) -> str:
    """Delete a branch. A DESTRUCTIVE MUTATION."""
    if branch == "main":
        raise ValueError("refusing to delete main")
    _BRANCHES.discard(branch)
    return f"deleted branch {branch} in {repo}"


if __name__ == "__main__":
    mcp.run()
