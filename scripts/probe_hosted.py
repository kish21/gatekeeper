"""Probe a HOSTED GateKeeper gateway — the M3.3 acceptance test, run from OUTSIDE the cloud.

    python -m scripts.probe_hosted --url https://<fqdn>

Where ``scripts.demo_enterprise`` runs the enterprise story against a LOCAL uvicorn it starts
itself, this drives the SAME governed pipeline over the public internet against a real deployment.
Nothing is faked: real DNS, real TLS at the platform ingress, real HTTP transport, real Cedar
policy, real hash-chained ledger on the mounted volume.

It asserts the five claims a hosted gateway must survive, and exits non-zero if any fails:

  T1  LIVE            GET /healthz answers over public HTTPS
  T2  GOVERNED LIST   an operator's tools/list returns the proxied surface
  T3  ALLOW           operator reads welcome.txt              -> forwarded
  T4  DENY (RBAC)     a read-only principal's write           -> refused, never forwarded
  T5  DENY (IDENTITY) an unknown bearer token                 -> refused, fail-closed
  T6  OBSERVABLE      GET /metrics returns Prometheus text

The tokens default to the image's DEMO static tokens (``config/identities.yaml`` — intentionally
fake placeholders, smoke-test only). Override them via ``--operator-token`` / ``--readonly-token``
once the deployment is switched to OIDC, and the same probe validates real IdP-issued JWTs.

READ-ONLY against your data: the only mutation attempted is the one that MUST be denied (T4). If
T4 ever reports ALLOW, that is a governance failure, not a passing test.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from rich.console import Console
from rich.table import Table

# The image's DEMO identities (config/identities.yaml). Placeholders, never real credentials.
DEFAULT_OPERATOR_TOKEN = "dev-token-alice-REPLACE-ME"  # noqa: S105 - fake placeholder
DEFAULT_READONLY_TOKEN = "dev-token-bob-REPLACE-ME"  # noqa: S105 - fake placeholder
DEMO_SAMPLE_FILE = "welcome.txt"
HTTP_TIMEOUT_S = 30.0


class Probe:
    """Accumulates PASS/FAIL rows so one failure never hides the rest of the report."""

    def __init__(self, console: Console) -> None:
        self._console = console
        self._rows: list[tuple[str, str, bool, str]] = []

    def record(self, test: str, claim: str, *, passed: bool, evidence: str) -> None:
        self._rows.append((test, claim, passed, evidence))
        mark = "[bold green]PASS[/]" if passed else "[bold red]FAIL[/]"
        self._console.print(f"  {mark}  {test:<18} {evidence}")

    @property
    def failed(self) -> int:
        return sum(1 for *_, passed, _ in self._rows if not passed)

    def report(self) -> None:
        table = Table(title="M3.3 hosted-deploy acceptance", show_lines=False)
        table.add_column("Test")
        table.add_column("What it proves")
        table.add_column("Result")
        for test, claim, passed, _ in self._rows:
            table.add_row(test, claim, "[green]PASS[/]" if passed else "[red]FAIL[/]")
        self._console.print()
        self._console.print(table)


@asynccontextmanager
async def _client(base: str, token: str) -> AsyncIterator[ClientSession]:
    """An initialized MCP client session carrying ``Authorization: Bearer <token>`` per request."""
    headers = {"Authorization": f"Bearer {token}"}
    async with streamablehttp_client(f"{base}/mcp", headers=headers) as (read, write, _sid):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _text(result: types.CallToolResult) -> str:
    return "".join(b.text for b in result.content if isinstance(b, types.TextContent)).strip()


def _root_cause(exc: BaseException, depth: int = 0) -> str:
    """Unwrap ExceptionGroup / __cause__ chains — 'unhandled errors in a TaskGroup' says nothing.

    anyio wraps transport failures in an ExceptionGroup, so the surface message hides the HTTP
    status (a 421 Host rejection and a DNS failure look identical). Report the innermost error.
    """
    if depth > 6:
        return f"{type(exc).__name__}: {exc}"
    inner = getattr(exc, "exceptions", None)
    if inner:
        return _root_cause(inner[0], depth + 1)
    if exc.__cause__ is not None:
        return _root_cause(exc.__cause__, depth + 1)
    return f"{type(exc).__name__}: {exc}"


async def _governed_call(
    base: str, token: str, tool: str, arguments: dict[str, Any]
) -> tuple[str, str]:
    """Drive one governed call. Returns (outcome, evidence); never raises.

    Outcome is one of ``allowed`` / ``denied`` / ``error``. The three are kept DISTINCT on purpose:
    a transport failure is NOT a governance denial. Collapsing them lets a broken connection score
    as a passing deny test — a false green that would make the whole probe worthless.
    """
    try:
        async with _client(base, token) as session:
            result = await session.call_tool(tool, arguments)
            detail = _text(result) or "(no message)"
            return ("denied" if result.isError else "allowed", detail[:140])
    except Exception as exc:  # noqa: BLE001 - reported as an inconclusive error, never as a deny
        return ("error", _root_cause(exc)[:140])


async def run(base: str, operator_token: str, readonly_token: str) -> int:
    console = Console()
    probe = Probe(console)
    console.rule(f"[bold]Probing {base}")

    # --- T1 live over public HTTPS ---------------------------------------------------------
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as http:
        try:
            health = await http.get(f"{base}/healthz")
            ok = health.status_code == 200 and health.json().get("status") == "ok"
            probe.record(
                "T1 LIVE",
                "reachable over public HTTPS",
                passed=ok,
                evidence=f"GET /healthz -> {health.status_code} {health.text[:60]}",
            )
        except Exception as exc:  # noqa: BLE001
            probe.record(
                "T1 LIVE",
                "reachable over public HTTPS",
                passed=False,
                evidence=f"{type(exc).__name__}: {str(exc)[:100]}",
            )
            probe.report()
            console.print("\n[red]Gateway unreachable — later tests skipped.[/]")
            return 1

    # --- T2 governed tool surface ----------------------------------------------------------
    try:
        async with _client(base, operator_token) as session:
            listed = await session.list_tools()
        names = sorted(t.name for t in listed.tools)
        probe.record(
            "T2 GOVERNED LIST",
            "operator sees the proxied surface",
            passed=bool(names),
            evidence=f"{len(names)} tools: {', '.join(names[:6])}",
        )
    except Exception as exc:  # noqa: BLE001
        probe.record(
            "T2 GOVERNED LIST",
            "operator sees the proxied surface",
            passed=False,
            evidence=_root_cause(exc)[:140],
        )

    # --- T3 allow --------------------------------------------------------------------------
    outcome, detail = await _governed_call(
        base, operator_token, "read_file", {"path": DEMO_SAMPLE_FILE}
    )
    probe.record(
        "T3 ALLOW",
        "operator read is forwarded",
        passed=outcome == "allowed",
        evidence=f"read {DEMO_SAMPLE_FILE} ok" if outcome == "allowed" else f"{outcome}: {detail}",
    )

    # --- T4 deny by policy (the money shot) ------------------------------------------------
    # PASS requires a REAL governed denial. An `error` outcome is a failed probe, not a passing
    # deny — a transport failure must never be reported as governance working.
    outcome, detail = await _governed_call(
        base,
        readonly_token,
        "write_file",
        {"path": "probe-should-never-exist.txt", "content": "if you can read this, RBAC failed"},
    )
    probe.record(
        "T4 DENY (RBAC)",
        "read-only write refused, never forwarded",
        passed=outcome == "denied",
        evidence={
            "denied": f"refused: {detail}",
            "allowed": "[bold red]WRITE WAS ALLOWED - governance failure[/]",
            "error": f"[yellow]inconclusive - never reached the policy: {detail}[/]",
        }[outcome],
    )

    # --- T5 deny by identity ---------------------------------------------------------------
    outcome, detail = await _governed_call(
        base, "not-a-real-token-probe", "read_file", {"path": DEMO_SAMPLE_FILE}
    )
    probe.record(
        "T5 DENY (IDENTITY)",
        "unknown bearer refused, fail-closed",
        passed=outcome == "denied",
        evidence={
            "denied": f"refused: {detail}",
            "allowed": "[bold red]UNKNOWN TOKEN WAS ALLOWED[/]",
            "error": f"[yellow]inconclusive - never reached identity: {detail}[/]",
        }[outcome],
    )

    # --- T6 observable ---------------------------------------------------------------------
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as http:
        try:
            metrics = await http.get(f"{base}/metrics")
            ok = metrics.status_code == 200 and "gatekeeper" in metrics.text
            lines = [ln for ln in metrics.text.splitlines() if ln and not ln.startswith("#")]
            probe.record(
                "T6 OBSERVABLE",
                "/metrics serves Prometheus text",
                passed=ok,
                evidence=f"{len(lines)} series, e.g. {lines[0][:70] if lines else 'none'}",
            )
        except Exception as exc:  # noqa: BLE001
            probe.record(
                "T6 OBSERVABLE",
                "/metrics serves Prometheus text",
                passed=False,
                evidence=f"{type(exc).__name__}: {str(exc)[:100]}",
            )

    probe.report()
    if probe.failed:
        console.print(f"\n[bold red]{probe.failed} test(s) FAILED.[/]")
        return 1
    console.print(
        "\n[bold green]All checks passed.[/] Now confirm the AUDIT side inside the container:\n"
        '  az containerapp exec -n gatekeeper -g gatekeeper-rg --command "gatekeeper tail"\n'
        '  az containerapp exec -n gatekeeper -g gatekeeper-rg --command "gatekeeper verify"\n'
        "The tail must show the ALLOW and both DENYs above; verify must report the chain intact."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--url", required=True, help="Gateway base URL, e.g. https://<fqdn> (no trailing /mcp)"
    )
    parser.add_argument(
        "--operator-token", default=DEFAULT_OPERATOR_TOKEN, help="bearer for the ALLOW case"
    )
    parser.add_argument(
        "--readonly-token", default=DEFAULT_READONLY_TOKEN, help="bearer for the RBAC DENY case"
    )
    args = parser.parse_args()
    base = args.url.rstrip("/").removesuffix("/mcp")
    return asyncio.run(run(base, args.operator_token, args.readonly_token))


if __name__ == "__main__":
    sys.exit(main())
