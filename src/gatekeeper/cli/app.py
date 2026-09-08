"""Operator CLI (Typer).

gatekeeper init      # one-time setup: secrets into .env, ledger created, demo files seeded
gatekeeper doctor    # check everything and print the MCP host config to paste
gatekeeper serve     # run the governed gateway (MCP transport)
gatekeeper tail      # tail the audit ledger
gatekeeper verify    # prove the hash-chained ledger is intact
gatekeeper show ID   # show the decision recorded for one call
gatekeeper stats     # allow/deny counts from the ledger
gatekeeper pending   # writes waiting for a human
gatekeeper approve ID / deny ID   # decide one
gatekeeper ui        # the same, as a web page (approvals, activity, trust, servers)
"""

from __future__ import annotations

import getpass
import importlib.util
import json
import os
import secrets
import shutil
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import typer
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from gatekeeper.adapters.approval.sql import ApprovalStateError
from gatekeeper.adapters.ledger.factory import open_ledger
from gatekeeper.adapters.ledger.sql import SqlLedgerStore
from gatekeeper.config.loader import (
    ENV_FILE,
    ConfigError,
    Settings,
    boot,
    get_settings,
    ledger_target,
    load_config,
    policy_dir,
    validate_security,
)
from gatekeeper.db.base import is_url, redact_url
from gatekeeper.domain.approval_rules import approver_rules_from_config
from gatekeeper.domain.errors import ApprovalRefused
from gatekeeper.gateway.factory import DEFAULT_APPROVAL_TIMEOUT_S
from gatekeeper.infra.logging import configure_logging, get_logger
from gatekeeper.schemas.approval import Approver
from gatekeeper.schemas.enums import ApprovalStatus, ApproverMethod, Verdict
from gatekeeper.schemas.ledger import LedgerEntry

app = typer.Typer(
    help="GateKeeperAI — verifiable governance gateway for MCP.", no_args_is_help=True
)
_console = Console()
#: Errors/diagnostics go here. For `serve`, stdout is the MCP JSON-RPC channel — any human text on
#: it corrupts the protocol (an MCP host reports "not valid JSON"), so failures must use stderr.
_err_console = Console(stderr=True)

# --- demo sandbox constants --------------------------------------------------
#: Env var + default naming the demo_file_server sandbox. Mirrors examples/demo_file_server.py (the
#: governed target) so the seeded dir is exactly the one that server reads/writes.
_DEMO_SANDBOX_ENV = "DEMO_FILE_ROOT"
_DEMO_SANDBOX_DEFAULT = "./.gatekeeper/demo_sandbox"
_DEMO_SAMPLE_FILE = "welcome.txt"
_DEMO_SAMPLE_TEXT = (
    "Hello from GateKeeperAI. This file is served by the governed demo_file_server, "
    "so `read_file welcome.txt` works the moment the gateway is up.\n"
)

#: Env keys `init` fills in when they are missing or empty (never overwriting a set value).
_ENV_HMAC = "GATEKEEPER_HMAC_KEY"
_ENV_AGENT_TOKEN = "GATEKEEPER_AGENT_TOKEN"  # noqa: S105 — a variable NAME, not a value
_ENV_HMAC_PREVIOUS = "GATEKEEPER_HMAC_KEY_PREVIOUS"


def _ledger_label(config: dict[str, Any]) -> str:
    """Where the ledger lives, safe to print: a file path, or a password-redacted Postgres URL."""
    target = ledger_target(config)
    return target if not is_url(target) else f"{redact_url(target)}  (postgres)"


def _durability_check(config: dict[str, Any]) -> tuple[str, bool, str]:
    """Is the audit trail going to survive this deployment?

    A SQLite file is right on one machine and wrong the moment the gateway is a container that can
    be replaced: the file goes with it, and on an SMB share it corrupts instead of failing loudly.
    So a network-facing gateway on the file ledger is reported as a FAILED check with the fix,
    rather than as a footnote someone reads after losing an audit trail.
    """
    target = ledger_target(config)
    listens_on_network = bool(
        config["platform"].get("transport", {}).get("http_allow_non_loopback", False)
    )
    if is_url(target):
        return ("ledger durability", True, "postgres: survives a restart, safe with many replicas")
    if listens_on_network:
        return (
            "ledger durability",
            False,
            "this gateway is network-facing but keeps its ledger in a local SQLite file, which is "
            "lost when the container is replaced. Set GATEKEEPER_LEDGER_URL to a Postgres database",
        )
    return ("ledger durability", True, "sqlite file: fine for one machine (loopback only)")


def _notification_check(config: dict[str, Any], settings: Settings) -> tuple[str, bool, str]:
    """If writes are held for a person, is any person actually told?

    On your own machine, watching the desk is a fair way to work, so this only reports. For a
    gateway a team shares, it fails: an approver who is not told is an approver who does not
    decide, and every held write then dies of timeout — a governance feature that silently
    degrades into an outage is worse than one that is switched off on purpose.
    """
    approval = config["product"].get("approval") or {}
    holds_writes = str(approval.get("writes", "off")).lower() == "require"
    shared = bool(config["platform"].get("transport", {}).get("http_allow_non_loopback", False))
    timeout = approval.get("timeout_s", DEFAULT_APPROVAL_TIMEOUT_S)
    if not holds_writes:
        return ("approval notifications", True, "not needed: writes are not held for a person")
    if settings.approval_webhook or settings.alert_webhook:
        where = settings.desk_url or "no GATEKEEPER_DESK_URL set: the message says what, not where"
        return ("approval notifications", True, f"held writes are announced ({where})")
    unheard = (
        "nothing announces a held write, so somebody has to be watching the desk when it "
        f"arrives or it is denied after {timeout}s. Set GATEKEEPER_APPROVAL_WEBHOOK"
    )
    if shared:
        return ("approval notifications", False, unheard)
    return ("approval notifications", True, f"watching the desk yourself is fine here; {unheard}")


@contextmanager
def _opened_ledger() -> Iterator[SqlLedgerStore]:
    """Open the ledger, map a misconfig to exit 2, and always close it (shared by commands)."""
    try:
        store = open_ledger()
    except ConfigError as exc:
        _console.print(f"[bold red][ERROR] {exc}[/]")
        raise typer.Exit(code=2) from exc
    try:
        yield store
    finally:
        store.close()


# --- init -------------------------------------------------------------------------------------
def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _upsert_env(path: Path, updates: dict[str, str]) -> list[str]:
    """Set each key in ``updates`` in the env file, replacing an empty value in place and
    appending a missing key. A key that already has a value is left alone. Returns keys written."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    written: list[str] = []
    for key, value in updates.items():
        replaced = False
        for i, line in enumerate(lines):
            if line.split("=", 1)[0].strip() == key:
                current = line.split("=", 1)[1].strip() if "=" in line else ""
                if current:
                    replaced = True  # keep the user's value
                    break
                lines[i] = f"{key}={value}"
                replaced = True
                written.append(key)
                break
        if not replaced:
            lines.append(f"{key}={value}")
            written.append(key)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return written


def _replace_env(path: Path, updates: dict[str, str]) -> None:
    """Set each key in ``updates``, OVERWRITING any existing value.

    Distinct from ``_upsert_env``, which never touches a value someone already set — right for
    first-run setup, wrong for a rotation, whose entire purpose is to replace the value that is
    there. Keeping the two apart means neither can quietly do the other's job.
    """
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    remaining = dict(updates)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            lines[i] = f"{key}={remaining.pop(key)}"
    lines.extend(f"{key}={value}" for key, value in remaining.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _first_token(identities: list[dict[str, Any]], role: str) -> str:
    for ident in identities:
        if str(ident.get("role", "")) == role and ident.get("token"):
            return str(ident["token"])
    return ""


def _seed_demo_sandbox(root_dir: Path) -> Path:
    """Create the demo sandbox + a sample file (idempotent); return the resolved path."""
    configured = os.environ.get(_DEMO_SANDBOX_ENV)
    root = Path(configured).resolve() if configured else (root_dir / _DEMO_SANDBOX_DEFAULT)
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    sample = root / _DEMO_SAMPLE_FILE
    if not sample.exists():
        sample.write_text(_DEMO_SAMPLE_TEXT, encoding="utf-8")
    return root


@app.command()
def init() -> None:
    """One-time setup: write secrets to .env, create the ledger, seed the demo files.

    Safe to re-run: existing values in .env are kept, the ledger is migrated in place, the sample
    file is not overwritten. Exit 0 when ready, 2 if the config folder cannot be found.
    """
    configure_logging(get_settings().log_level)
    settings = get_settings()
    try:
        config = load_config(settings)
    except ConfigError as exc:
        _console.print(f"[bold red][ERROR] {exc}[/]")
        raise typer.Exit(code=2) from exc

    root = settings.project_root
    env_path = root / ENV_FILE
    existing = _read_env_file(env_path)
    updates: dict[str, str] = {}
    if not existing.get(_ENV_HMAC) and not os.environ.get(_ENV_HMAC):
        updates[_ENV_HMAC] = secrets.token_hex(32)
    if not existing.get(_ENV_AGENT_TOKEN) and not os.environ.get(_ENV_AGENT_TOKEN):
        token = _first_token(config["identities"], "operator")
        if token:
            updates[_ENV_AGENT_TOKEN] = token
    written = _upsert_env(env_path, updates) if updates else []
    get_settings.cache_clear()  # the ledger below must see the key that was just written

    try:
        settings, config = boot()
        with _opened_ledger() as store:
            entries = store.verify().checked
    except ConfigError as exc:
        _console.print(f"[bold red][ERROR] {exc}[/]")
        raise typer.Exit(code=2) from exc
    sandbox = _seed_demo_sandbox(root)

    table = Table(title="GateKeeperAI - init", show_header=False, box=box.ASCII)
    table.add_row(
        "secrets file",
        f"{env_path}  ({'wrote ' + ', '.join(written) if written else 'kept as is'})",
    )
    table.add_row("audit ledger", f"{_ledger_label(config)}  ({entries} entries, chain intact)")
    table.add_row("demo sandbox", f"{sandbox} ({_DEMO_SAMPLE_FILE})")
    table.add_row("governed servers", ", ".join(str(u.get("name")) for u in config["upstreams"]))
    _console.print(table)
    _console.print(
        "Ready. Next: [bold]gatekeeper doctor[/] prints the config to paste into your MCP host."
    )


# --- doctor -----------------------------------------------------------------------------------
def _gatekeeper_executable() -> str:
    """Absolute path of the ``gatekeeper`` command an MCP host should launch.

    The one next to THIS interpreter comes first: that is the environment `doctor` just checked.
    A same-named binary elsewhere on PATH may be another install with other packages.
    """
    # sys.prefix is the active environment (a venv's python is often a symlink elsewhere, so
    # resolving sys.executable would point at the wrong bin directory).
    bin_dir = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")
    candidate = bin_dir / ("gatekeeper.exe" if os.name == "nt" else "gatekeeper")
    if candidate.is_file():
        return str(candidate.resolve())
    found = shutil.which("gatekeeper")
    return str(Path(found).resolve()) if found else str(candidate)


def _launcher_ok(command: list[str], root: Path) -> tuple[bool, str]:
    """Can this upstream's launcher be found? Bare python is pinned to this interpreter, and a
    ``-m`` module may be an installed package or a module under the project root (servers launch
    from there)."""
    if not command:
        return False, "no command"
    head = command[0]
    if head in ("python", "python3") or head == sys.executable:
        if len(command) >= 3 and command[1] == "-m":
            module = command[2]
            in_project = (root / Path(*module.split("."))).with_suffix(".py").is_file() or (
                root / Path(*module.split(".")) / "__init__.py"
            ).is_file()
            installed = importlib.util.find_spec(module.split(".")[0]) is not None
            if in_project:
                return True, f"module {module} (project)"
            return installed, f"module {module} {'found' if installed else 'NOT installed'}"
        return True, "this interpreter"
    if shutil.which(head) or Path(head).is_file():
        return True, f"{head} found"
    return False, f"{head} not on PATH"


def host_config(settings: Settings) -> dict[str, Any]:
    """The ``mcpServers`` block an MCP host (Claude Desktop, an IDE) needs — absolute paths only."""
    return {
        "mcpServers": {
            "gatekeeper": {
                "command": _gatekeeper_executable(),
                "args": ["serve"],
                "env": {"GATEKEEPER_CONFIG_DIR": str(settings.config_dir.resolve())},
            }
        }
    }


@app.command()
def doctor(
    as_json: bool = typer.Option(False, "--json", help="Print only the MCP host config JSON."),
) -> None:
    """Check secrets, ledger, policy, identities and servers; print the MCP host config.

    Exit 0 when everything passes, 1 when a check fails, 2 when the gateway cannot even boot.
    """
    configure_logging(get_settings().log_level)
    log = get_logger("gatekeeper.doctor")
    settings = get_settings()
    checks: list[tuple[str, bool, str]] = []

    try:
        config = load_config(settings)
    except ConfigError as exc:
        _console.print(f"[bold red][ERROR] GateKeeperAI cannot boot:[/]\n{exc}")
        raise typer.Exit(code=2) from exc

    try:
        validate_security(settings)
        checks.append(("HMAC key", True, "set (chain key, validated)"))
    except ConfigError as exc:
        checks.append(("HMAC key", False, str(exc).split(". ")[0]))

    if checks[-1][1]:
        try:
            with _opened_ledger() as store:
                result = store.verify()
            checks.append(
                (
                    "audit ledger",
                    result.ok,
                    f"{_ledger_label(config)} ({result.checked} entries, {result.detail})",
                )
            )
        except typer.Exit:
            checks.append(("audit ledger", False, "cannot open (see error above)"))
    else:
        checks.append(("audit ledger", False, "skipped: no HMAC key"))

    checks.append(_durability_check(config))
    checks.append(_notification_check(config, settings))

    try:
        from gatekeeper.adapters.policy.cedar import CedarPolicyEngine

        CedarPolicyEngine.from_config(policy_dir(config))
        checks.append(("policy", True, f"{policy_dir(config)} parses"))
    except ConfigError as exc:
        checks.append(("policy", False, str(exc)))

    identity_kind = config["platform"].get("adapters", {}).get("identity", "static_token")
    if identity_kind == "static_token":
        tokens = {str(i.get("token")): i for i in config["identities"]}
        who = tokens.get(settings.agent_token)
        if who:
            checks.append(
                ("agent token", True, f"{who.get('principal')} ({who.get('role')}) for stdio")
            )
        else:
            checks.append(
                (
                    "agent token",
                    False,
                    f"{_ENV_AGENT_TOKEN} is unset or matches no identity "
                    "(run `gatekeeper init`, or set a token from config/identities.yaml)",
                )
            )
    else:
        checks.append(("identity", True, f"{identity_kind} (per-request tokens)"))

    for upstream in config["upstreams"]:
        ok, detail = _launcher_ok(
            [str(p) for p in upstream.get("command", [])], settings.project_root
        )
        checks.append((f"server: {upstream.get('name')}", ok, detail))

    all_ok = all(ok for _, ok, _ in checks)
    if not as_json:
        table = Table(title="GateKeeperAI - doctor", box=box.ASCII)
        table.add_column("check")
        table.add_column("status")
        table.add_column("detail")
        for name, ok, detail in checks:
            table.add_row(name, "[green]OK[/]" if ok else "[red]FAIL[/]", detail)
        _console.print(table)
        _console.print(
            "Paste this into your MCP host (Claude Desktop: claude_desktop_config.json; "
            "other hosts: their mcpServers block):"
        )
    _console.print(json.dumps(host_config(settings), indent=2))
    log.info("doctor", extra={"ok": all_ok, "checks": [(n, ok) for n, ok, _ in checks]})
    if not all_ok:
        raise typer.Exit(code=1)


@app.command()
def health() -> None:
    """Boot through the startup guard and show the resolved config (a liveness-style check).

    Lighter than ``doctor``: proves the gateway CAN boot (key present, config parses) without
    checking the agent token or launching anything. Exit 0, or 2 on a boot failure.
    """
    configure_logging(get_settings().log_level)
    try:
        settings, config = boot()
    except ConfigError as exc:
        _console.print(f"[bold red][ERROR] GateKeeperAI cannot boot:[/]\n{exc}")
        raise typer.Exit(code=2) from exc
    platform = config["platform"]
    adapters = platform.get("adapters", {})
    table = Table(title="GateKeeperAI - health", show_header=False, box=box.ASCII)
    table.add_row("env", settings.env)
    table.add_row("HMAC key", "set (validated, fail-closed)")
    table.add_row("audit ledger", _ledger_label(config))
    table.add_row("policy dir", policy_dir(config))
    table.add_row("adapters", ", ".join(f"{k}={v}" for k, v in adapters.items()))
    table.add_row("transport", str(platform.get("transport", {}).get("mode", "stdio")))
    table.add_row("servers registered", str(len(config["upstreams"])))
    table.add_row("identities", str(len(config["identities"])))
    _console.print(table)
    _console.print("For a full check-up (token, ledger, policy, servers): gatekeeper doctor")


# --- serve ------------------------------------------------------------------------------------
@app.command()
def serve(
    transport: str | None = typer.Option(
        None,
        "--transport",
        help="stdio | http. Default: transport.mode in platform.yaml / GATEKEEPER_TRANSPORT.",
    ),
) -> None:
    """Run the governed gateway (transparent MCP proxy) over stdio or Streamable HTTP.

    Exit 2 on misconfig (no HMAC key / non-loopback HTTP bind without the ack / placeholder
    tokens on an exposed bind) or, for stdio, an unauthenticated agent token.
    """
    import anyio

    from gatekeeper.domain.errors import IdentityError
    from gatekeeper.transport.http_server import serve_http
    from gatekeeper.transport.stdio_server import serve_stdio

    try:
        mode = transport or str(load_config()["platform"].get("transport", {}).get("mode", "stdio"))
        if mode == "stdio":
            anyio.run(serve_stdio)
        elif mode == "http":
            anyio.run(serve_http)
        else:  # fail-loud: an unknown transport is a misconfig, not a silent default
            raise ConfigError(f"unknown transport {mode!r} (expected stdio | http)")
    except (ConfigError, IdentityError) as exc:
        # stderr, NOT stdout: stdout is the MCP protocol channel here (see _err_console).
        _err_console.print(f"[bold red][ERROR] GateKeeperAI cannot serve:[/]\n{exc}")
        if isinstance(exc, IdentityError):
            _err_console.print(
                f"Set {_ENV_AGENT_TOKEN} in .env to a token from config/identities.yaml "
                "(`gatekeeper init` does this), then run `gatekeeper doctor`."
            )
        raise typer.Exit(code=2) from exc


# --- ledger commands --------------------------------------------------------------------------
@app.command()
def tail(
    limit: int = 20,
    principal: str | None = None,
    with_id: bool = typer.Option(
        False, "--with-id", help="Add a call_id column (the natural key for `show <call_id>`)."
    ),
) -> None:
    """Tail the audit ledger (most recent shown last)."""
    configure_logging(get_settings().log_level)
    with _opened_ledger() as store:
        entries = store.read(limit=limit, principal=principal)
    if not entries:
        _console.print("(ledger is empty)")
        return
    table = Table(title="audit ledger (recent)", box=box.ASCII)
    # call_id leads when shown: it's the key the operator copies into `show`.
    columns = (
        ("seq", "call_id", "ts", "principal", "tool", "verdict")
        if with_id
        else ("seq", "ts", "principal", "tool", "verdict")
    )
    for col in columns:
        table.add_column(col, overflow="fold", no_wrap=(col == "call_id"))
    for e in reversed(entries):  # oldest -> newest
        row = [str(e.seq), e.ts[:19], e.principal, f"{e.upstream}:{e.tool}", str(e.verdict)]
        if with_id:
            row.insert(1, e.call_id[:12])  # a prefix is enough for `show`
        table.add_row(*row)
    _console.print(table)
    if not with_id:
        _console.print("Add --with-id to see the id each row passes to `gatekeeper show`.")
    else:
        _console.print("Inspect one: gatekeeper show <id>   (a prefix is enough)")


@app.command()
def verify(
    expect_head: str | None = typer.Option(
        None,
        "--expect-head",
        help="A head hash printed by an earlier verify. Detects records removed from the end.",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Machine-readable result, for a cron job or a monitoring check."
    ),
) -> None:
    """Verify audit-ledger integrity. Exit 0=intact, 1=tampered, 2=misconfig.

    Pin the printed head somewhere the ledger's host cannot reach (a ticket, a separate log);
    pass it back with --expect-head to also detect a truncated chain. Run it on a schedule with
    --json: the exit code is the alert, the JSON is the evidence.
    """
    configure_logging(get_settings().log_level)
    log = get_logger("gatekeeper.verify")
    with _opened_ledger() as store:
        result = store.verify(expected_head=expect_head)
    if as_json:
        _console.print_json(result.model_dump_json())
        if not result.ok:
            raise typer.Exit(code=1)
        return
    if result.ok:
        _console.print(f"[bold green]OK[/] ledger intact - {result.checked} entries verified")
        _console.print(f"head: {result.head}")
        log.info("verify ok", extra={"checked": result.checked, "head": result.head})
        return
    where = f"broken at seq={result.broken_at}: " if result.broken_at is not None else ""
    _console.print(
        f"[bold red]TAMPERED[/] {where}{result.detail} (verified {result.checked} before the break)"
    )
    log.error("verify failed", extra={"broken_at": result.broken_at, "detail": result.detail})
    # Alert hook: a tampered ledger is THE signal this product exists for — page someone.
    # Fail-safe (never raises, exit code stays 1) and off when no webhook is configured.
    from gatekeeper.infra.alerts import WebhookAlerter

    WebhookAlerter(get_settings().alert_webhook).fire(
        "verify_failure",
        {"broken_at": result.broken_at, "detail": result.detail, "checked": result.checked},
    )
    raise typer.Exit(code=1)


# --- taking the record somewhere else: the SIEM, the archive, a new key ------------------------
def _as_jsonl(entry: LedgerEntry) -> str:
    return entry.model_dump_json()


def _as_csv(entry: LedgerEntry) -> str:
    values = [
        str(entry.seq),
        entry.ts,
        entry.call_id,
        entry.principal,
        entry.role,
        f"{entry.upstream}:{entry.tool}",
        entry.action_kind.value,
        entry.verdict.value,
        entry.reason.replace('"', "'"),
        entry.result_summary.replace('"', "'"),
        entry.entry_hash or "",
    ]
    return ",".join(f'"{v}"' for v in values)


def _as_cef(entry: LedgerEntry) -> str:
    """ArcSight CEF — the format most SIEMs ingest without a custom parser."""
    severity = {"deny": 7, "pending": 4, "allow": 2}.get(entry.verdict.value, 3)
    extension = " ".join(
        f"{k}={v}"
        for k, v in {
            "rt": entry.ts,
            "suser": entry.principal,
            "sproc": f"{entry.upstream}:{entry.tool}",
            "act": entry.verdict.value,
            "cs1Label": "reason",
            "cs1": entry.reason.replace("=", "-").replace("|", "/"),
            "cs2Label": "callId",
            "cs2": entry.call_id,
            "cn1Label": "seq",
            "cn1": entry.seq,
        }.items()
    )
    return (
        f"CEF:0|GateKeeperAI|gatekeeper|1|{entry.action_kind.value}.{entry.verdict.value}"
        f"|{entry.upstream}:{entry.tool}|{severity}|{extension}"
    )


_FORMATTERS = {"jsonl": _as_jsonl, "csv": _as_csv, "cef": _as_cef}
_CSV_HEADER = "seq,ts,call_id,principal,role,tool,action,verdict,reason,result,entry_hash"


def _write_entries(entries: Iterable[LedgerEntry], fmt: str, out: Path | None) -> int:
    """Stream entries in ``fmt`` to a file or stdout. Returns how many were written."""
    formatter = _FORMATTERS[fmt]
    handle = out.open("w", encoding="utf-8") if out else None
    written = 0
    try:
        if fmt == "csv":
            print(_CSV_HEADER, file=handle)
        for entry in entries:
            print(formatter(entry), file=handle)
            written += 1
    finally:
        if handle is not None:
            handle.close()
    return written


@app.command()
def export(
    since: str = typer.Option("", "--since", help="UTC date or timestamp, e.g. 2026-01-01."),
    until: str = typer.Option("", "--until", help="Exclusive upper bound, same format."),
    fmt: str = typer.Option("jsonl", "--format", help="jsonl | csv | cef"),
    out: Path | None = typer.Option(None, "--out", help="Write here instead of stdout."),
) -> None:
    """Export the audit trail for your SIEM, an auditor, or a spreadsheet.

    The ledger is the durable record; this is a copy of it in a shape something else can read.
    Streamed in batches, so exporting a year costs bounded memory. Nothing is removed — see
    `gatekeeper archive` for retention.
    """
    configure_logging(get_settings().log_level)
    if fmt not in _FORMATTERS:
        _console.print(f"[bold red][ERROR][/] unknown format {fmt!r} (jsonl | csv | cef)")
        raise typer.Exit(code=2)
    with _opened_ledger() as store:
        written = _write_entries(
            store.entries_between(since_ts=since or None, until_ts=until or None), fmt, out
        )
    if out:
        _console.print(f"exported {written} entries to {out} ({fmt})")


@app.command()
def archive(
    before: str = typer.Option(..., "--before", help="Archive entries older than this UTC date."),
    out: Path = typer.Option(..., "--out", help="Where the archived entries are written."),
    prune: bool = typer.Option(
        False,
        "--prune",
        help="Also REMOVE them from the ledger, leaving a signed checkpoint in their place.",
    ),
    note: str = typer.Option("", "--note", help="Why, recorded in the checkpoint."),
) -> None:
    """Archive old entries, and optionally remove them under a signed retention checkpoint.

    A hash chain proves nothing was removed; a retention policy exists to remove things. Rather
    than pretend those do not conflict, a prune records where the cut was and what the chain's
    state was at that point, and signs that statement with the ledger key. `verify` then resumes
    from the checkpoint and reports it — so the removal is accountable, and removing records
    WITHOUT such a signed account is still detected as tampering.

    The archive file is always written first. A deletion with nowhere to read the records back
    from is not retention.
    """
    configure_logging(get_settings().log_level)
    log = get_logger("gatekeeper.archive")
    with _opened_ledger() as store:
        written = _write_entries(store.entries_before(before), "jsonl", out)
        if written == 0:
            _console.print(f"nothing older than {before}; no archive written")
            raise typer.Exit(code=0)
        _console.print(f"archived {written} entries to {out}")
        if not prune:
            _console.print("Nothing was removed. Re-run with --prune to apply retention.")
            return
        try:
            checkpoint = store.prune_before(before, archive_path=str(out), note=note)
        except ValueError as exc:
            _console.print(f"[bold yellow]nothing pruned[/] {exc}")
            raise typer.Exit(code=1) from exc
        result = store.verify()

    _console.print(
        f"[bold]removed[/] {checkpoint.pruned_count} entries through seq "
        f"{checkpoint.through_seq}, under a signed checkpoint"
    )
    _console.print(f"verify -> {'OK' if result.ok else 'FAILED'}: {escape(result.detail)}")
    log.info(
        "retention applied",
        extra={
            "through_seq": checkpoint.through_seq,
            "pruned": checkpoint.pruned_count,
            "archive": str(out),
            "verify_ok": result.ok,
        },
    )


@app.command(name="rotate-key")
def rotate_key(
    yes: bool = typer.Option(False, "--yes", help="Do it without asking."),
) -> None:
    """Rotate the ledger's chain key, keeping every existing record verifiable.

    Generates a new key, moves the current one into GATEKEEPER_HMAC_KEY_PREVIOUS, and writes both
    back to .env. New entries are signed with the new key; older ones keep the fingerprint of the
    key that signed them, so one `verify` still walks the whole chain.

    Keep the retired keys. Deleting one makes every record it signed unverifiable — which looks
    exactly like tampering, and cannot be undone.
    """
    configure_logging(get_settings().log_level)
    settings = get_settings()
    if not settings.hmac_key.strip():
        _console.print("[bold red][ERROR][/] there is no key to rotate. Run `gatekeeper init`.")
        raise typer.Exit(code=2)
    if not yes and not typer.confirm("Rotate the ledger chain key now?"):
        _console.print("nothing changed")
        raise typer.Exit(code=1)

    env_path = settings.project_root / ENV_FILE
    existing = _read_env_file(env_path)
    retired = [k for k in (existing.get("GATEKEEPER_HMAC_KEY_PREVIOUS", ""), "") if k]
    previous = ",".join([settings.hmac_key, *retired])
    _replace_env(env_path, {_ENV_HMAC: secrets.token_hex(32), _ENV_HMAC_PREVIOUS: previous})
    get_settings.cache_clear()

    with _opened_ledger() as store:
        result = store.verify()
    _console.print(f"[bold green]rotated[/] new chain key written to {env_path}")
    _console.print(f"the retired key is kept in {_ENV_HMAC_PREVIOUS} so old records still verify")
    _console.print(f"verify -> {'OK' if result.ok else 'FAILED'}: {escape(result.detail)}")
    if not result.ok:
        raise typer.Exit(code=1)


@app.command()
def show(call_id: str) -> None:
    """Show everything recorded for one call: who, what, each decision, and the outcome.

    Accepts the full call id or a prefix (as printed by ``tail --with-id``). Exit 0=found, 1=no
    such call or ambiguous prefix, 2=misconfig. Pairs with ``verify``: ``verify`` proves the whole
    chain is intact, ``show`` inspects one recorded call.
    """
    configure_logging(get_settings().log_level)
    log = get_logger("gatekeeper.show")
    if len(call_id) < 4:
        _console.print("[bold yellow]too short[/] give at least 4 characters of the call id")
        raise typer.Exit(code=1)
    with _opened_ledger() as store:
        entries, matches = store.lifecycle(call_id)  # bound as a query parameter (no injection)
    if matches > 1:
        _console.print(
            f"[bold yellow]ambiguous[/] {matches} calls start with {call_id!r}; "
            "give more characters"
        )
        raise typer.Exit(code=1)
    if not entries:
        _console.print(f"[bold yellow]not found[/] no audit entry for call_id={call_id!r}")
        log.info("show miss", extra={"call_id": call_id})
        raise typer.Exit(code=1)

    # Every field below is PII-safe by construction: the ledger stores principal/role (never the
    # token) and HMAC digests (never the key); raw arguments/output are never persisted.
    first, last = entries[0], entries[-1]
    final = next((e for e in reversed(entries) if e.verdict is not Verdict.PENDING), last)
    verdict_color = {Verdict.ALLOW: "green", Verdict.DENY: "red"}.get(final.verdict, "yellow")
    table = Table(title=f"call {first.call_id}", show_header=False, box=box.ASCII)
    table.add_row("principal", f"{first.principal} (role={first.role}, tenant={first.tenant})")
    table.add_row("tool", f"{first.upstream}:{first.tool}")
    table.add_row("action", str(first.action_kind))
    table.add_row("final verdict", f"[bold {verdict_color}]{final.verdict}[/]")
    table.add_row("payload_hash", first.payload_hash)
    _console.print(table)

    steps = Table(title="what happened, in order", box=box.ASCII)
    for col in ("seq", "ts (UTC)", "verdict", "reason", "result"):
        steps.add_column(col, overflow="fold")
    for e in entries:
        steps.add_row(
            str(e.seq), e.ts[:19], str(e.verdict), escape(e.reason), escape(e.result_summary or "-")
        )
    _console.print(steps)
    _console.print(
        f"chain: prev_hash {last.prev_hash or '-'}\n       entry_hash {last.entry_hash or '-'}"
    )
    _console.print("Run `gatekeeper verify` to confirm the chain that contains these entries.")


@app.command()
def stats(limit: int = 1000) -> None:
    """Platform-health snapshot from the audit ledger.

    Calls, allow/deny counts and rates, denies by principal, and busiest tools — derived from
    the last ``limit`` ledger entries (decision entries only, so a call is counted once).
    Live process metrics (overhead p95 vs budget) are on the HTTP transport's ``/metrics``.
    """
    configure_logging(get_settings().log_level)
    with _opened_ledger() as store:
        entries = store.read(limit=limit)
    # A call yields a decision entry and (when allowed+forwarded) an outcome entry that repeats
    # the verdict. Count each call_id once — its decision — so rates mean "of all calls".
    decisions: dict[str, Any] = {}
    for e in entries:  # read() returns newest-first; keep the OLDEST decided entry per call
        if e.verdict is Verdict.PENDING and e.call_id in decisions:
            continue  # the hold entry precedes the decision; the decision already won
        decisions[e.call_id] = e
    calls = list(decisions.values())
    if not calls:
        _console.print("(ledger is empty)")
        return
    allows = [e for e in calls if e.verdict is Verdict.ALLOW]
    denies = [e for e in calls if e.verdict is Verdict.DENY]
    waiting = [e for e in calls if e.verdict is Verdict.PENDING]

    table = Table(title=f"platform health - last {len(calls)} calls", box=box.ASCII)
    table.add_column("metric")
    table.add_column("value")
    table.add_row("calls", str(len(calls)))
    table.add_row("allowed", f"{len(allows)} ({len(allows) / len(calls):.0%})")
    table.add_row("denied", f"{len(denies)} ({len(denies) / len(calls):.0%})")
    if waiting:
        table.add_row("awaiting approval", str(len(waiting)))
    deny_by_principal = Counter(e.principal for e in denies)
    table.add_row(
        "denies by principal",
        ", ".join(f"{p}={n}" for p, n in deny_by_principal.most_common(5)) or "-",
    )
    top_tools = Counter(f"{e.upstream}:{e.tool}" for e in calls)
    table.add_row("busiest tools", ", ".join(f"{t}={n}" for t, n in top_tools.most_common(5)))
    table.add_row("window", f"{calls[-1].ts} .. {calls[0].ts}")
    _console.print(table)
    _console.print(
        "Live process metrics (overhead p95 vs budget): GET /metrics on the HTTP transport. "
        "Run `gatekeeper verify` to prove this history is untampered."
    )


# --- human approval ---------------------------------------------------------------------------
def _approver(by: str | None) -> Approver:
    """Who is deciding at a terminal on the gateway host.

    ``--by`` names a colleague you are deciding on behalf of; without it the OS user is recorded.
    Either way the method is ``console``: the proof is a shell on the gateway host, which is a real
    (and privileged) thing to have, but it is not a login — and the ledger says so.
    """
    return Approver(id=by or getpass.getuser(), method=ApproverMethod.CONSOLE)


@app.command()
def pending() -> None:
    """List the writes currently held for a human decision."""
    configure_logging(get_settings().log_level)
    from gatekeeper.gateway.factory import open_approvals

    with _opened_ledger() as store:
        queue = open_approvals(store)
        try:
            requests = queue.list_pending()
        finally:
            queue.close()
    if not requests:
        _console.print("(nothing waiting for approval)")
        return
    table = Table(title="writes waiting for a human", box=box.ASCII)
    for col in ("id", "since (UTC)", "who", "role", "tool", "arguments"):
        table.add_column(col, overflow="fold", no_wrap=(col == "id"))
    for r in requests:
        table.add_row(
            r.id,
            r.ts[11:19],
            r.principal,
            r.role,
            f"{r.upstream}:{r.tool}",
            escape(r.arguments_preview),
        )
    _console.print(table)
    _console.print(
        "Decide with: gatekeeper approve <id>   or   gatekeeper deny <id> --reason '...'"
    )


def _decide(request_id: str, status: ApprovalStatus, by: str | None, note: str) -> None:
    configure_logging(get_settings().log_level)
    log = get_logger("gatekeeper.approval")
    from gatekeeper.gateway.factory import open_approvals

    approver = _approver(by)
    rules = approver_rules_from_config(load_config()["product"], require_verified=False)
    with _opened_ledger() as store:
        queue = open_approvals(store)
        try:
            held = queue.get(request_id)
            if held is None:
                _console.print(f"[bold yellow]not decided[/] no approval request {request_id!r}")
                raise typer.Exit(code=1)
            # Checked before anything is written, so a refusal leaves the write held for someone
            # who is allowed to release it — the same rules the desk applies.
            rules.check(held, approver)
            decided = queue.decide(
                request_id, status, by=approver.id, note=note, method=approver.method.value
            )
        except ApprovalRefused as exc:
            _console.print(f"[bold yellow]not decided[/] {exc}")
            raise typer.Exit(code=1) from exc
        except ApprovalStateError as exc:
            _console.print(f"[bold yellow]not decided[/] {exc}")
            raise typer.Exit(code=1) from exc
        finally:
            queue.close()
    color = "green" if status is ApprovalStatus.APPROVED else "red"
    _console.print(
        f"[bold {color}]{status.value.upper()}[/] request {decided.id}: "
        f"{decided.principal} -> {decided.upstream}:{decided.tool} "
        f"(by {decided.decided_by}, {decided.decided_method})"
    )
    _console.print(
        "The gateway records this decision in the ledger and acts on it within a second."
    )
    log.info(
        "approval decided",
        extra={
            "request": decided.id,
            "status": status.value,
            "by": decided.decided_by,
            "method": decided.decided_method,
        },
    )


@app.command()
def approve(
    request_id: str,
    by: str | None = typer.Option(None, "--by", help="Who is approving (default: your OS user)."),
    note: str = typer.Option("", "--reason", help="Optional note recorded with the decision."),
) -> None:
    """Approve a held write: it is recorded as approved by you, then forwarded."""
    _decide(request_id, ApprovalStatus.APPROVED, by, note)


@app.command()
def deny(
    request_id: str,
    by: str | None = typer.Option(None, "--by", help="Who is denying (default: your OS user)."),
    note: str = typer.Option("", "--reason", help="Why; recorded in the ledger."),
) -> None:
    """Deny a held write: recorded as denied by you; the tool is never called."""
    _decide(request_id, ApprovalStatus.DENIED, by, note)


@app.command()
def ui(
    port: int | None = typer.Option(None, "--port", help="Default: GATEKEEPER_UI_PORT or 8770."),
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Bind address. Beyond loopback needs GATEKEEPER_UI_TOKEN."
    ),
) -> None:
    """Open the guard's desk in a browser: approvals, activity, trust check, governed servers.

    Runs next to a gateway an MCP host launched over stdio (both share the ledger database), or
    on its own. Exit 2 on misconfig.
    """
    import uvicorn

    from gatekeeper.ui import create_ui_app, ui_token_for_bind

    configure_logging(get_settings().log_level)
    try:
        boot()  # fail-closed HMAC key + config present; the ledger opens per request
        token = ui_token_for_bind(host)
        if host not in ("127.0.0.1", "localhost", "::1") and not token:
            raise ConfigError(
                "Binding the UI beyond this machine requires GATEKEEPER_UI_TOKEN (the page asks "
                "for it once). Refusing to expose the approvals desk without one."
            )
    except ConfigError as exc:
        _console.print(f"[bold red][ERROR] {exc}[/]")
        raise typer.Exit(code=2) from exc
    chosen = port or get_settings().ui_port
    _console.print(f"GateKeeper desk: [bold]http://{host}:{chosen}/ui[/]   (Ctrl-C to stop)")
    loopback = host in ("127.0.0.1", "localhost", "::1")
    uvicorn.run(
        # Beyond loopback a decision needs a proven identity: the desk refuses a typed-in name.
        create_ui_app(open_ledger, token=token, require_verified=not loopback),
        host=host,
        port=chosen,
        log_level="warning",
    )


# --- seed-demo (kept for existing scripts; `init` supersedes it) -----------------------------
@app.command(name="seed-demo", hidden=True)
def seed_demo() -> None:
    """Seed the demo sandbox and show what is governed (no secrets needed). Prefer ``init``."""
    configure_logging(get_settings().log_level)
    log = get_logger("gatekeeper.seed-demo")
    settings = get_settings()
    try:
        config = load_config(settings)  # no security guard: prep step, runnable before .env exists
    except ConfigError as exc:
        _console.print(f"[bold red][ERROR] {exc}[/]")
        raise typer.Exit(code=2) from exc

    sandbox = _seed_demo_sandbox(settings.project_root)
    _print_governed(config)
    steps = Table(title="run the demo", box=box.ASCII)
    steps.add_column("#")
    steps.add_column("command")
    steps.add_row("1", "gatekeeper init      # writes GATEKEEPER_HMAC_KEY + agent token to .env")
    steps.add_row("2", "gatekeeper doctor    # checks everything, prints the MCP host config")
    steps.add_row("3", "make serve           # or let your MCP host launch it (doctor's JSON)")
    steps.add_row("4", "make tail / make verify / gatekeeper show <call_id>")
    _console.print(steps)
    _console.print(f"demo sandbox ready: {sandbox} (sample file: {_DEMO_SAMPLE_FILE})")
    # markup=False: the literal "[demo]" must not be parsed as a Rich style tag.
    _console.print(
        "Both upstreams above are governed with ZERO gateway code. The 'time' upstream is a real "
        'third-party server; install its package to launch it: pip install -e ".[demo]"',
        markup=False,
    )
    log.info(
        "seed-demo ready",
        extra={"upstreams": len(config["upstreams"]), "identities": len(config["identities"])},
    )


def _print_governed(config: dict[str, Any]) -> None:
    """Show what is governed, read back from config (reinforces 'config-driven, zero code')."""
    upstreams = Table(title="governed upstreams (config/upstreams.yaml)", box=box.ASCII)
    for col in ("name", "transport", "launch / url"):
        upstreams.add_column(col)
    for u in config["upstreams"]:
        launch = " ".join(str(p) for p in u.get("command", [])) or str(u.get("url", "-"))
        upstreams.add_row(str(u.get("name", "?")), str(u.get("transport", "?")), launch)
    _console.print(upstreams)

    # Identities: principal + role ONLY - the bearer token is a secret and is never printed.
    identities = Table(
        title="identities (config/identities.yaml - role shown, token never printed)", box=box.ASCII
    )
    for col in ("principal", "role"):
        identities.add_column(col)
    for p in config["identities"]:
        identities.add_row(str(p.get("principal", "?")), str(p.get("role", "?")))
    _console.print(identities)


if __name__ == "__main__":
    app()
