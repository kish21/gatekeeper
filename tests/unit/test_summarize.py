"""Unit tests for the upstream result summarizer — it must NOT leak raw output into the ledger."""

from __future__ import annotations

from mcp import types

from gatekeeper.adapters.upstream.mcp_client import _summarize


def _result(text: str, *, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)], isError=is_error
    )


def test_success_summary_is_status_only_not_content() -> None:
    secret = "TOP-SECRET-FILE-CONTENTS"
    summary = _summarize(_result(secret))
    assert secret not in summary  # raw output never reaches the ledger
    assert summary.startswith("ok:") and "chars" in summary


def test_error_summary_keeps_truncated_diagnostic() -> None:
    summary = _summarize(_result("file not found: a.txt", is_error=True))
    assert summary.startswith("error:") and "file not found" in summary


def test_empty_error_summary_has_a_marker() -> None:
    assert _summarize(types.CallToolResult(content=[], isError=True)) == "error"
