"""Operator CLI (Typer) — the M1.4 surface.

gatekeeper health    # walking-skeleton health path: boot through the guard, show resolved config
gatekeeper serve     # run the governed gateway (MCP transport)        [/build]
gatekeeper tail      # tail the audit ledger                           [/build]
gatekeeper verify    # prove the hash-chained ledger is intact         [/build]
gatekeeper show ID   # show the decision recorded for one call         [/build]
gatekeeper seed-demo # write example config for a local demo           [/build]
"""

from __future__ import annotations

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from gatekeeper.config.loader import ConfigError, boot, get_settings
from gatekeeper.infra.logging import configure_logging, get_logger

app = typer.Typer(
    help="GateKeeperAI — verifiable governance gateway for MCP.", no_args_is_help=True
)
_console = Console()
_TODO = "Implemented in /build."


@app.command()
def health() -> None:
    """Boot through the startup guard and show resolved config (proves config flows)."""
    configure_logging(get_settings().log_level)
    log = get_logger("gatekeeper.health")
    try:
        settings, config = boot()
    except ConfigError as exc:
        # fail-loud: clear message + non-zero exit, never a silent insecure boot.
        log.error("health check failed", extra={"reason": str(exc)})
        _console.print(f"[bold red][ERROR] GateKeeperAI cannot boot:[/]\n{exc}")
        raise typer.Exit(code=2) from exc

    platform = config["platform"]
    adapters = platform.get("adapters", {})
    # Read values BACK from each source to prove they actually flow (no dead config):
    # box.ASCII => deterministic, cp1252-safe borders on every terminal (incl. legacy Windows).
    table = Table(title="GateKeeperAI - health", show_header=False, box=box.ASCII)
    table.add_row("env (.env)", settings.env)
    table.add_row("log level (.env)", settings.log_level)
    table.add_row("HMAC key", "set (validated, fail-closed)")
    table.add_row("ledger path (platform.yaml)", str(platform.get("ledger", {}).get("path", "?")))
    table.add_row(
        "hash algo (platform.yaml)", str(platform.get("ledger", {}).get("hash_algo", "?"))
    )
    table.add_row("adapters (platform.yaml)", ", ".join(f"{k}={v}" for k, v in adapters.items()))
    table.add_row("upstreams registered", str(len(config["upstreams"])))
    table.add_row("identities (dev map)", str(len(config["identities"])))
    _console.print(table)
    log.info(
        "health ok",
        extra={
            "env": settings.env,
            "adapters": adapters,
            "upstreams": len(config["upstreams"]),
            "identities": len(config["identities"]),
        },
    )


@app.command()
def serve() -> None:
    """Run the governed gateway."""
    raise NotImplementedError(_TODO)


@app.command()
def tail(limit: int = 20) -> None:
    """Tail the audit ledger."""
    raise NotImplementedError(_TODO)


@app.command()
def verify() -> None:
    """Verify audit-ledger integrity (walk the hash-chain)."""
    raise NotImplementedError(_TODO)


@app.command()
def show(call_id: str) -> None:
    """Show the recorded decision for one call id."""
    raise NotImplementedError(_TODO)


@app.command(name="seed-demo")
def seed_demo() -> None:
    """Write example upstream/identity/policy config for a local demo."""
    raise NotImplementedError(_TODO)


if __name__ == "__main__":
    app()
