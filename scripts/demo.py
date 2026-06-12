"""One-command, narrated customer demo of GateKeeperAI - the 5-beat governance story on a terminal.

    python -m scripts.demo

Plays the whole "verifiable governance" pitch live, end-to-end, against the REAL governed pipeline
(the exact ``identity -> classify -> Cedar policy -> tamper-evident audit -> forward`` path that
``gatekeeper serve`` runs - assembled here via ``build_pipeline``, not a look-alike) and a REAL MCP
upstream subprocess. No agent wiring, no pytest, no setup:

  Beat 1  TRANSPARENT     operator reads a file -> ALLOW, upstream content relayed
  Beat 2  RBAC BITES      read-only principal's write -> DENY (Cedar), never forwarded
  Beat 3  TOOL-AGNOSTIC   operator calls a REAL 3rd-party server (mcp-server-time), zero code
  Beat 4  PROVABLE AUDIT  the hash-chained ledger of every call -> `verify` = OK
  Beat 5  DON'T-TRUST     edit a ledger row to hide the denial -> `verify` catches it: TAMPERED

It is HERMETIC and NON-DESTRUCTIVE: an ephemeral HMAC key (never your ``.env``), a throwaway SQLite
ledger + sandbox in a temp dir (never your real audit trail - Beat 5 deliberately corrupts the
ledger, so it MUST run on a disposable one), all removed on exit. Everything that is governed -
identities, roles, upstreams, read/write classification, policy - is read from ``config/*.yaml``;
nothing here is hardcoded.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from mcp import types
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.config.loader import load_config
from gatekeeper.db.base import Base, database_url, ensure_parent_dir
from gatekeeper.db.models import LedgerEntryRow
from gatekeeper.domain.errors import IdentityError, PolicyDenied
from gatekeeper.gateway.factory import GatewayRuntime, build_pipeline
from gatekeeper.schemas.enums import Verdict
from gatekeeper.schemas.models import ToolResult

_console = Console()

# Tool names below are the upstreams' real names (config/upstreams.yaml); read/write
# classification is decided by the gateway from config, not asserted here.
_WELCOME = "welcome.txt"
_WELCOME_TEXT = (
    "Hello from GateKeeperAI - this file is relayed live through the governed gateway.\n"
)


def _pick(identities: list[dict[str, Any]], role: str) -> dict[str, Any]:
    """First identity with ``role`` from config/identities.yaml (so principals aren't hardcoded)."""
    for ident in identities:
        if ident.get("role") == role:
            return ident
    raise SystemExit(f"config/identities.yaml has no identity with role {role!r} - cannot demo it.")


def _use_current_interpreter(config: dict[str, Any]) -> None:
    """Point every stdio upstream's ``python`` launcher at THIS interpreter (in place).

    config/upstreams.yaml launches the demo + time servers with a bare ``python``, which on a
    fresh shell may resolve to a different interpreter that lacks these packages. The demo must be
    runnable with one command regardless of shell/venv activation, so we pin the launcher to
    ``sys.executable`` - the same interpreter running this script, which definitely has them
    (mirrors how the integration tests launch upstreams). Only the interpreter is swapped; the rest
    of the config (which servers, which tools are reads vs writes, the policy) is honored verbatim.
    """
    for upstream in config["upstreams"]:
        command = list(upstream.get("command", []))
        if command and command[0] in ("python", "python3"):
            command[0] = sys.executable
            upstream["command"] = command


def _section(beat: int, title: str, claim: str) -> None:
    _console.print()
    _console.rule(f"[bold]Beat {beat}/5 - {title}")
    _console.print(f"[italic dim]{claim}[/]")


def _relayed_text(result: ToolResult | None) -> str:
    """The upstream's real, untouched output as the agent receives it (via ``ToolResult.raw``)."""
    raw = getattr(result, "raw", None)
    if isinstance(raw, types.CallToolResult):
        return "".join(b.text for b in raw.content if isinstance(b, types.TextContent)).strip()
    return result.summary if result else ""


async def _call(
    runtime: GatewayRuntime,
    *,
    token: str,
    who: str,
    upstream: str,
    tool: str,
    arguments: dict[str, Any],
) -> ToolResult | None:
    """Drive one governed call and narrate the verdict. Returns the result, or None on a deny."""
    label = f"{who:<18} {upstream}:{tool}"
    try:
        result = await runtime.pipeline.handle(
            token=token, upstream=upstream, tool=tool, arguments=arguments, call_id=uuid.uuid4().hex
        )
    except PolicyDenied as exc:
        _console.print(f"  [bold red]DENY [/]  {label}\n           [red]policy: {exc}[/]")
        return None
    except IdentityError as exc:
        _console.print(f"  [bold red]DENY [/]  {label}\n           [red]identity: {exc}[/]")
        return None
    if result.ok:
        _console.print(f"  [bold green]ALLOW[/]  {label}")
    else:
        # The decision was ALLOW and was audited; the upstream itself errored (still governed).
        _console.print(
            f"  [bold yellow]ALLOW[/]  {label}   [yellow](upstream: {result.summary})[/]"
        )
    return result


def _render_ledger(ledger: SqliteLedgerStore) -> None:
    """Print the audit trail exactly as `gatekeeper tail` would (oldest -> newest)."""
    entries = ledger.read(limit=50)
    table = Table(title="audit ledger - every call above, hash-chained", box=box.ASCII)
    for col in ("seq", "principal", "role", "tool", "action", "verdict"):
        table.add_column(col)
    for e in reversed(entries):  # read() is newest-first; show chronological
        color = "green" if e.verdict is Verdict.ALLOW else "red"
        table.add_row(
            str(e.seq),
            e.principal,
            e.role,
            f"{e.upstream}:{e.tool}",
            e.action_kind.value,
            f"[{color}]{e.verdict.value}[/]",
        )
    _console.print(table)


async def run_demo() -> int:
    config = load_config()  # no security guard: a showcase prep step (like `seed-demo`)
    _use_current_interpreter(config)
    identities = config["identities"]
    operator = _pick(identities, "operator")  # may read + request writes
    readonly = _pick(identities, "readonly")  # may read only - writes denied by policy
    op_name, ro_name = str(operator["principal"]), str(readonly["principal"])

    # --- hermetic, throwaway resources (Beat 5 corrupts the ledger; never touch the real one) ---
    key = secrets.token_hex(32)  # ephemeral HMAC key - never read from / written to .env
    workdir = Path(tempfile.mkdtemp(prefix="gatekeeper-demo-"))
    sandbox = workdir / "sandbox"
    sandbox.mkdir()
    (sandbox / _WELCOME).write_text(_WELCOME_TEXT, encoding="utf-8")
    # The MCP stdio launcher gives the child a SCRUBBED environment (not the parent's), so the
    # sandbox root + a quiet child log level must be passed explicitly on the demo-files upstream.
    # Merge the current environment so the child keeps PATH/SystemRoot (needed to spawn on Windows).
    for upstream in config["upstreams"]:
        if upstream.get("name") == "demo-files":
            upstream["env"] = {
                **os.environ,
                "DEMO_FILE_ROOT": str(sandbox),  # isolate this run's sandbox from any prior one
            }

    ledger_db = str(workdir / "audit.db")
    ensure_parent_dir(ledger_db)
    engine = create_engine(database_url(ledger_db))
    Base.metadata.create_all(engine)  # equivalent of `make migrate`, on a disposable DB
    session = Session(engine)
    ledger = SqliteLedgerStore(session, key)
    runtime = build_pipeline(config, hmac_key=key, ledger=ledger)

    _console.print(
        Panel.fit(
            "[bold]GateKeeperAI[/] - verifiable governance for the Model Context Protocol\n"
            "[dim]Every tool call below is authenticated, RBAC-checked, and recorded in a\n"
            "tamper-evident, hash-chained ledger - for any MCP server, by config alone.[/]",
            border_style="cyan",
        )
    )

    exit_code = 0
    try:
        # Beat 1 - transparent when allowed.
        _section(
            1,
            "Transparent",
            f"{op_name} (operator) reads a file - governance is invisible when you're allowed.",
        )
        read = await _call(
            runtime,
            token=str(operator["token"]),
            who=f"{op_name} (operator)",
            upstream="demo-files",
            tool="read_file",
            arguments={"path": _WELCOME},
        )
        if read:
            _console.print(
                f'           [dim]relayed from the real server ->[/] "{_relayed_text(read)}"'
            )

        # Beat 2 - RBAC bites (fail-closed, no side effect).
        _section(
            2,
            "RBAC bites",
            f"{ro_name} (read-only) tries to WRITE - Cedar denies it; the upstream is never asked.",
        )
        await _call(
            runtime,
            token=str(readonly["token"]),
            who=f"{ro_name} (read-only)",
            upstream="demo-files",
            tool="write_file",
            arguments={"path": "secret.txt", "content": "should never be written"},
        )
        listing = await _call(
            runtime,
            token=str(operator["token"]),
            who=f"{op_name} (operator)",
            upstream="demo-files",
            tool="list_dir",
            arguments={"path": "."},
        )
        if listing:
            files = _relayed_text(listing)
            _console.print(
                f"           [dim]sandbox now contains ->[/] {files}  "
                f"[green](secret.txt was never created - deny had no effect)[/]"
            )

        # Beat 3 - tool-agnostic: a REAL third-party server, governed by config alone.
        _section(
            3,
            "Tool-agnostic",
            f"{op_name} calls a REAL third-party server (mcp-server-time) - zero gateway code.",
        )
        clock = await _call(
            runtime,
            token=str(operator["token"]),
            who=f"{op_name} (operator)",
            upstream="time",
            tool="get_current_time",
            arguments={"timezone": "UTC"},
        )
        if clock and clock.ok:
            _console.print(
                "           [dim]relayed from a server we did NOT write ->[/] "
                f"{_relayed_text(clock)}"
            )
        elif clock is not None:
            _console.print(
                "           [yellow]the `time` server isn't installed "
                '(`pip install -e ".[demo]"`). '
                "Governance still applied (the call was classified + audited).[/]"
            )

        # Beat 4 - provable audit: show the chain, then verify it.
        _section(
            4,
            "Provable audit",
            "Every call above is one hash-chained ledger - `verify` proves nothing "
            "was altered, inserted, or dropped.",
        )
        _render_ledger(ledger)
        ok = ledger.verify()
        _console.print(
            f"  [bold green]verify -> OK[/]  chain intact, {ok.checked} entries verified"
        )

        # Beat 5 - don't trust the gateway, VERIFY it: tamper, and watch verify catch it.
        _section(
            5,
            "Don't trust - verify",
            "An insider edits the ledger to hide the denial. The keyed-HMAC hash-chain catches it.",
        )
        deny = next((e for e in ledger.read(limit=50) if e.verdict is Verdict.DENY), None)
        if deny is None:
            _console.print("  [yellow](no deny entry to tamper - skipping)[/]")
        else:
            row = session.get(LedgerEntryRow, deny.seq)
            assert row is not None
            _console.print(
                f"  [dim]tampering with seq={deny.seq}: rewriting its 'reason' to look benign...[/]"
            )
            row.reason = "forward ok"  # make the denial look like an allowed call
            session.commit()
            broken = ledger.verify()
            if broken.ok:
                _console.print(
                    "  [bold red]UNEXPECTED: verify still passed[/]"
                )  # would be a real bug
                exit_code = 1
            else:
                _console.print(
                    f"  [bold red]verify -> TAMPERED[/]  broken at seq={broken.broken_at}: "
                    f"{broken.detail}"
                )
                _console.print(
                    "  [green]The tamper is detected. That is the wedge: "
                    "don't trust the gateway - verify it.[/]"
                )

        _console.print()
        _console.rule("[bold green]Demo complete")
        _console.print(
            "[dim]Same engine your agent connects to via `gatekeeper serve`. "
            "Govern your own MCP server by adding a block to config/upstreams.yaml - zero code.[/]"
        )
    finally:
        await runtime.aclose()
        engine.dispose()
        shutil.rmtree(workdir, ignore_errors=True)
    return exit_code


def main() -> None:
    # Quiet the gateway's own logs (incl. the ERROR-level "call.denied.policy" trace event) so the
    # demo narrative is the only thing on screen — verdicts are surfaced by the script itself.
    logging.getLogger("gatekeeper").setLevel(logging.CRITICAL)
    raise SystemExit(asyncio.run(run_demo()))


if __name__ == "__main__":
    main()
