"""One-command, narrated ENTERPRISE demo — the hosted shape: real login (OIDC) over HTTP.

    python -m scripts.demo_enterprise        (or: make demo-enterprise)

Where ``scripts.demo`` shows the LOCAL governance story (stdio, hand-made dev tokens), this shows
the ENTERPRISE shape the Azure deployment runs (see ``docs/SHOWCASE-AZURE.md``): the SAME governed
pipeline, but reached over real HTTP and authenticated with validated IdP-style JWTs
(signature / audience / expiry checked, group -> role mapped) instead of dev tokens.

A small LOCAL fake IdP stands in for Entra ID / Okta — only the JWKS key *fetch* is faked; the
signature / claim validation, the HTTP transport, Cedar policy, the tamper-evident ledger, and the
``/metrics`` surface are all REAL (same plumbing as ``tests/integration/test_oidc_http.py``).

  Beat 1  HOSTED + REAL LOGIN   an operator (real JWT, "Ops" group) reads over HTTP -> ALLOW
  Beat 2  RBAC OVER HTTP        a read-only user's write -> DENY (Cedar), never forwarded
  Beat 3  FAIL-CLOSED IDENTITY  an expired token, and an unmapped group -> DENY, recorded
  Beat 4  LIVE HEALTH           GET /metrics -> Prometheus text (calls, deny rate, p95 vs budget)
  Beat 5  PROVABLE AUDIT        the hash-chained ledger over HTTP -> verify OK; tamper -> caught

HERMETIC + NON-DESTRUCTIVE: an ephemeral HMAC key (never your ``.env``), a throwaway ledger +
sandbox in a temp dir (Beat 5 corrupts the ledger, so it MUST be disposable), a loopback uvicorn on
an ephemeral port — all removed on exit. Governance (roles, upstreams, classification, policy) is
read from ``config/*.yaml``; the fake IdP is the ONLY stand-in, and it is clearly the local one.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import shutil
import socket
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import httpx
import jwt
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from gatekeeper.adapters.identity.oidc import OidcIdentityResolver
from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.adapters.policy.cedar import CedarPolicyEngine
from gatekeeper.adapters.upstream.mcp_client import McpUpstreamClient
from gatekeeper.config.loader import load_config, secret_source
from gatekeeper.db.base import Base, database_url, ensure_parent_dir
from gatekeeper.db.models import LedgerEntryRow
from gatekeeper.domain.classify import ActionClassifier
from gatekeeper.gateway.factory import GatewayRuntime
from gatekeeper.gateway.pipeline import GatewayPipeline
from gatekeeper.infra.metrics import GatewayMetrics
from gatekeeper.schemas.enums import Verdict
from gatekeeper.transport.http_server import create_app
from gatekeeper.transport.surface import build_tool_index

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# --- the LOCAL fake IdP (stands in for Entra ID / Okta) ---------------------------------------
# Mirrors tests/unit/test_identity_oidc.py: a locally generated RSA key signs RS256 JWTs and ONLY
# the JWKS key fetch is stubbed, so signature / audience / expiry / group validation runs the REAL
# PyJWT path with zero network. These are the fake IdP's coordinates, not gateway config.
_ISSUER = "https://idp.local/demo-tenant"
_AUDIENCE = "api://gatekeeper-demo"
_GROUP_OPS = "group-ops"
_GROUP_RO = "group-readonly"
_GROUP_ROLE_MAP = {_GROUP_OPS: "operator", _GROUP_RO: "readonly"}

_WELCOME = "welcome.txt"
_WELCOME_TEXT = "Hello over HTTP, authenticated by a real login - relayed through the gateway.\n"


class _StubJwks:
    """Stand in for ``PyJWKClient``: always serve the local fake IdP's public key (no network)."""

    def __init__(self, public_key: Any) -> None:
        self._key = public_key

    def get_signing_key_from_jwt(self, token: str) -> Any:
        return SimpleNamespace(key=self._key)


def _make_idp() -> tuple[str, _StubJwks]:
    """Generate the local fake IdP: return (private-key PEM, a JWKS stub for its public half)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, _StubJwks(key.public_key())


def _mint(pem: str, *, sub: str, groups: list[str], exp_delta_s: int = 600) -> str:
    """Sign a real RS256 JWT as the local fake IdP would (the only stand-in in this demo)."""
    now = int(time.time())
    claims = {
        "sub": sub,
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "iat": now,
        "exp": now + exp_delta_s,
        "groups": groups,
    }
    return jwt.encode(claims, pem, algorithm="RS256")


# --- live-HTTP plumbing (mirror of tests/integration/http_harness.py; inlined to stay standalone) -
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@asynccontextmanager
async def _serving(
    runtime: GatewayRuntime, metrics: GatewayMetrics, *, budget_ms: float
) -> AsyncIterator[str]:
    """Serve the REAL governed app under uvicorn on a loopback ephemeral port (the hosted shape)."""
    index = await build_tool_index(runtime)
    app = create_app(runtime, index, path="/mcp", metrics=metrics, overhead_budget_ms=budget_ms)
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False)
    )
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(30):
            while not server.started:  # noqa: ASYNC110 — uvicorn exposes no readiness event
                await asyncio.sleep(0.02)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        async with asyncio.timeout(30):
            await task


@asynccontextmanager
async def _client(base: str, token: str) -> AsyncIterator[ClientSession]:
    """An initialized MCP client session carrying ``Authorization: Bearer <jwt>`` per request."""
    headers = {"Authorization": f"Bearer {token}"}
    async with streamablehttp_client(f"{base}/mcp", headers=headers) as (read, write, _sid):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


# --- narration --------------------------------------------------------------------------------
def _text(result: types.CallToolResult) -> str:
    return "".join(b.text for b in result.content if isinstance(b, types.TextContent)).strip()


def _section(console: Console, beat: int, title: str, claim: str) -> None:
    console.print()
    console.rule(f"[bold]Beat {beat}/5 - {title}")
    console.print(f"[italic dim]{claim}[/]")


async def _call(
    console: Console, session: ClientSession, *, who: str, tool: str, arguments: dict[str, Any]
) -> types.CallToolResult:
    """Drive one governed call over HTTP and narrate the verdict (never prints the token)."""
    result = await session.call_tool(tool, arguments)
    label = f"{who:<24} {tool}"
    if result.isError:
        console.print(f"  [bold red]DENY [/]  {label}\n           [red]{_text(result)}[/]")
    else:
        console.print(f"  [bold green]ALLOW[/]  {label}")
    return result


def _render_ledger(console: Console, ledger: SqliteLedgerStore) -> None:
    """Print the audit trail (oldest -> newest): principal + role come from the validated JWT."""
    entries = ledger.read(limit=50)
    table = Table(
        title="audit ledger over HTTP (principal + role come from the validated JWT)", box=box.ASCII
    )
    for col in ("seq", "principal", "role", "tool", "verdict"):
        table.add_column(col)
    for e in reversed(entries):  # read() is newest-first; show chronological
        color = "green" if e.verdict is Verdict.ALLOW else "red"
        table.add_row(
            str(e.seq),
            e.principal,
            e.role,
            f"{e.upstream}:{e.tool}",
            f"[{color}]{e.verdict.value}[/]",
        )
    console.print(table)


def _build_runtime(
    config: dict[str, Any],
    *,
    key: str,
    ledger: SqliteLedgerStore,
    metrics: GatewayMetrics,
    jwks: _StubJwks,
) -> GatewayRuntime:
    """Wire the governed runtime. The ONE swap vs scripts.demo: identity is real-IdP OIDC.

    classifier + policy + upstream are built from ``config`` (no hardcoding), exactly like the real
    factory; only the identity adapter is the OIDC resolver with the local fake IdP's JWKS stub.
    """
    write_detection = config["product"].get("write_detection", {})
    annotations = {
        str(u["name"]): {"writes": list(u.get("writes", [])), "reads": list(u.get("reads", []))}
        for u in config["upstreams"]
    }
    classifier = ActionClassifier(
        name_patterns=list(write_detection.get("name_patterns", [])),
        upstream_annotations=annotations,
    )
    policy = CedarPolicyEngine.from_config(
        config["platform"].get("policy", {}).get("dir", "policies")
    )
    upstream = McpUpstreamClient.from_config(
        config["upstreams"], timeout=30.0, secret_source=secret_source()
    )
    identity = OidcIdentityResolver(
        issuer=_ISSUER, audience=_AUDIENCE, group_role_map=_GROUP_ROLE_MAP, jwks_client=jwks
    )
    pipeline = GatewayPipeline(
        identity=identity,
        classifier=classifier,
        policy=policy,
        ledger=ledger,
        upstream=upstream,
        hmac_key=key,
        metrics=metrics,
    )
    return GatewayRuntime(pipeline=pipeline, identity=identity, upstream=upstream, ledger=ledger)


async def run_enterprise_demo(console: Console | None = None) -> int:
    console = console or Console()
    config = load_config()  # no security guard: a showcase prep step (like `seed-demo`)
    # Focus on the demo-files upstream (the third-party `time` server isn't needed here).
    config["upstreams"] = [u for u in config["upstreams"] if u.get("name") == "demo-files"]
    if not config["upstreams"]:
        console.print("[red]config/upstreams.yaml has no 'demo-files' upstream - cannot demo.[/]")
        return 2
    # Pin the upstream launcher to THIS interpreter (mirrors scripts.demo) so one command runs
    # regardless of shell/venv; only the interpreter is swapped, the rest of config is honored.
    for upstream_cfg in config["upstreams"]:
        command = list(upstream_cfg.get("command", []))
        if command and command[0] in ("python", "python3"):
            command[0] = sys.executable
            upstream_cfg["command"] = command

    pem, jwks = _make_idp()

    # --- hermetic, throwaway resources (Beat 5 corrupts the ledger; never touch the real one) ---
    key = secrets.token_hex(32)  # ephemeral HMAC key - never read from / written to .env
    workdir = Path(tempfile.mkdtemp(prefix="gatekeeper-edemo-"))
    sandbox = workdir / "sandbox"
    sandbox.mkdir()
    (sandbox / _WELCOME).write_text(_WELCOME_TEXT, encoding="utf-8")
    for upstream_cfg in config["upstreams"]:
        if upstream_cfg.get("name") == "demo-files":
            # The stdio launcher gives the child a scrubbed env; pass the sandbox root + keep PATH.
            upstream_cfg["env"] = {**os.environ, "DEMO_FILE_ROOT": str(sandbox)}

    ledger_db = str(workdir / "audit.db")
    ensure_parent_dir(ledger_db)
    engine = create_engine(database_url(ledger_db))
    Base.metadata.create_all(engine)  # equivalent of `make migrate`, on a disposable DB
    db_session = Session(engine)
    ledger = SqliteLedgerStore(db_session, key)
    metrics = GatewayMetrics()  # this run's live metrics; /metrics reads the same instance
    runtime = _build_runtime(config, key=key, ledger=ledger, metrics=metrics, jwks=jwks)
    budget_ms = float(config["platform"].get("perf", {}).get("overhead_p95_ms", 10.0))

    console.print(
        Panel.fit(
            "[bold]GateKeeperAI[/] - ENTERPRISE shape: governed over HTTP, real logins\n"
            "[dim]The same pipeline scripts.demo shows locally, now reached over real HTTP and\n"
            "authenticated with validated IdP JWTs (local fake IdP stands in for Entra/Okta).[/]",
            border_style="cyan",
        )
    )

    exit_code = 0
    try:
        async with _serving(runtime, metrics, budget_ms=budget_ms) as base:
            # Beat 1 - hosted + real login.
            _section(
                console,
                1,
                "Hosted + real login",
                "An operator signs in (real JWT, 'Ops' group) and reads a file - over HTTP.",
            )
            async with _client(
                base, _mint(pem, sub="alice@corp.example", groups=[_GROUP_OPS])
            ) as s:
                read = await _call(
                    console,
                    s,
                    who="alice (Ops -> operator)",
                    tool="read_file",
                    arguments={"path": _WELCOME},
                )
                if not read.isError:
                    console.print(
                        f'           [dim]relayed from the real server ->[/] "{_text(read)}"'
                    )

            # Beat 2 - RBAC bites over HTTP.
            _section(
                console,
                2,
                "RBAC over HTTP",
                "A read-only user tries to WRITE - Cedar denies it; never forwarded.",
            )
            async with _client(base, _mint(pem, sub="bob@corp.example", groups=[_GROUP_RO])) as s:
                await _call(
                    console,
                    s,
                    who="bob (Readonly)",
                    tool="write_file",
                    arguments={"path": "secret.txt", "content": "should never be written"},
                )

            # Beat 3 - identity is the IdP's call, fail-closed.
            _section(
                console,
                3,
                "Fail-closed identity",
                "An expired token, or an unmapped group -> DENY, recorded - never a default.",
            )
            expired = _mint(pem, sub="alice@corp.example", groups=[_GROUP_OPS], exp_delta_s=-60)
            async with _client(base, expired) as s:
                await _call(
                    console, s, who="expired token", tool="read_file", arguments={"path": _WELCOME}
                )
            unmapped = _mint(pem, sub="carol@corp.example", groups=["some-other-group"])
            async with _client(base, unmapped) as s:
                await _call(
                    console,
                    s,
                    who="carol (unmapped group)",
                    tool="read_file",
                    arguments={"path": _WELCOME},
                )
            console.print(
                "           [dim]Same person, mapped group -> a role; unmapped -> nothing. "
                "Group membership IS the control.[/]"
            )

            # Beat 4 - live health (the /metrics surface a real scraper reads).
            _section(
                console,
                4,
                "Live health",
                "Operators watch the gateway live - the same /metrics a Prometheus / Azure Monitor "
                "scraper reads.",
            )
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.get(f"{base}/metrics")
            console.print(
                Panel(resp.text.strip(), title="GET /metrics", border_style="magenta", expand=False)
            )

        # Beat 5 - provable audit (ledger ops are local; the server has stopped).
        _section(
            console,
            5,
            "Provable audit",
            "Every call above is one hash-chained ledger over the network - verify proves it, "
            "and catches tampering.",
        )
        _render_ledger(console, ledger)
        ok = ledger.verify()
        console.print(f"  [bold green]verify -> OK[/]  chain intact, {ok.checked} entries verified")
        deny = next((e for e in ledger.read(limit=50) if e.verdict is Verdict.DENY), None)
        if deny is None:
            console.print("  [yellow](no deny entry to tamper - skipping)[/]")
        else:
            row = db_session.get(LedgerEntryRow, deny.seq)
            assert row is not None
            console.print(f"  [dim]an insider edits seq={deny.seq} to hide the denial...[/]")
            row.reason = "forward ok"  # make the denial look benign
            db_session.commit()
            broken = ledger.verify()
            if broken.ok:
                console.print("  [bold red]UNEXPECTED: verify still passed[/]")  # a real bug
                exit_code = 1
            else:
                console.print(
                    f"  [bold red]verify -> TAMPERED[/]  broken at seq={broken.broken_at}: "
                    f"{broken.detail}"
                )
                console.print(
                    "  [green]Caught. The wedge holds over HTTP too: "
                    "don't trust the gateway - verify it.[/]"
                )

        console.print()
        console.rule("[bold green]Enterprise demo complete")
        console.print(
            "[dim]This is the shape the Azure deploy runs (docs/SHOWCASE-AZURE.md). Swap the\n"
            "local fake IdP for your Entra / Okta tenant by config - no code - then point\n"
            "agents at the HTTPS URL.[/]"
        )
    finally:
        await runtime.aclose()
        engine.dispose()
        shutil.rmtree(workdir, ignore_errors=True)
    return exit_code


def main() -> None:
    # Quiet the gateway's own logs so the demo narrative is the only thing on screen.
    logging.getLogger("gatekeeper").setLevel(logging.CRITICAL)
    raise SystemExit(asyncio.run(run_enterprise_demo()))


if __name__ == "__main__":
    main()
