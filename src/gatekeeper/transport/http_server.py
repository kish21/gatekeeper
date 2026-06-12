"""Streamable HTTP MCP transport — the network binding of the shared governed proxy surface.

MCP **Streamable HTTP** via the official SDK's ``StreamableHTTPSessionManager``, mounted in a
FastAPI app served by uvicorn — **one worker by construction** (ADR-007: the programmatic
``uvicorn.Server`` runs a single process/event loop, and the ledger's sync append contains no
``await``, so two appends can never interleave and the hash chain cannot race; no ``workers``
knob is exposed anywhere).

Transport stays logic-free (ADR-008): this module only EXTRACTS the per-request
``Authorization: Bearer`` token from the SDK request context; the **pipeline** resolves and
records it. A ``tools/call`` with a missing/invalid bearer still reaches the pipeline, which
ledgers the identity-deny and then refuses — never a silent transport-level 401.

Fail-closed exposure (ADR-009): default bind is loopback; a non-loopback
``transport.http_host`` refuses boot unless ``transport.http_allow_non_loopback: true`` is set
explicitly, which logs the ADR-006 bearer-replay warning. TLS is NOT terminated here — it
belongs to the cloud ingress (M3.3). SDK DNS-rebinding protection stays ON.
"""

from __future__ import annotations

import ipaddress
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import uvicorn
from fastapi import FastAPI
from mcp.server.lowlevel.server import request_ctx
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from gatekeeper.config.loader import ConfigError, get_settings, load_config
from gatekeeper.gateway.factory import GatewayRuntime, build_runtime
from gatekeeper.infra.logging import configure_logging, get_logger
from gatekeeper.infra.metrics import GatewayMetrics, default_metrics
from gatekeeper.transport.surface import build_proxy_server, build_tool_index

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.types import Receive, Scope, Send

# Defaults applied when a knob is absent from platform.yaml (same values are documented there).
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8765
_DEFAULT_PATH = "/mcp"
_DEFAULT_BUDGET_MS = 10.0  # perf.overhead_p95_ms fallback (ADR-001 budget)

#: Host-header values always acceptable on a loopback bind (any port — the bind is the guard).
_LOOPBACK_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]


def http_transport_config(config: dict[str, Any]) -> dict[str, Any]:
    """Read the ``transport.*`` HTTP knobs (with defaults) — one place, no scattered ``get``s."""
    transport = config["platform"].get("transport", {})
    return {
        "host": str(transport.get("http_host", _DEFAULT_HOST)),
        "port": int(transport.get("http_port", _DEFAULT_PORT)),
        "path": str(transport.get("http_path", _DEFAULT_PATH)),
        "allow_non_loopback": bool(transport.get("http_allow_non_loopback", False)),
        "allowed_origins": [str(o) for o in transport.get("http_allowed_origins", []) or []],
        # Extra Host-header values for the /mcp DNS-rebinding check (e.g. the public FQDN of a
        # hosted deployment: "gw.example.com:*"). Loopback hosts are always allowed.
        "allowed_hosts": [str(h) for h in transport.get("http_allowed_hosts", []) or []],
    }


def _is_loopback(host: str) -> bool:
    """True only for addresses that cannot be reached off-box. Unknown hostnames count as NOT
    loopback (fail-closed): we refuse rather than resolve-and-guess."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def ensure_exposure_acked(host: str, *, allow_non_loopback: bool) -> None:
    """ADR-009: refuse a non-loopback bind without an explicit config acknowledgement.

    Raises ``ConfigError`` (boot aborts) when ``host`` is network-reachable and
    ``transport.http_allow_non_loopback`` is not set. When it IS set, the caller logs the
    ADR-006 bearer-replay warning — exposure is then a recorded, deliberate decision.
    """
    if _is_loopback(host):
        return
    if not allow_non_loopback:
        raise ConfigError(
            f"transport.http_host={host!r} is not a loopback address. Bearer tokens are "
            "replayable if exposed beyond the local machine (ADR-006/ADR-009). Refusing to "
            "boot (fail-closed). To expose deliberately, set "
            "transport.http_allow_non_loopback: true in platform.yaml — and terminate TLS "
            "in front of the gateway (see the M3.3 deploy guide)."
        )


def extract_bearer_token() -> str:
    """The per-request ``Authorization: Bearer`` value for the CURRENT MCP request, or "".

    Reads the starlette request the SDK attaches to the request context (verified present for
    Streamable HTTP in mcp 1.27.2). "" makes the identity resolver fail closed; the token value
    itself is never logged (it is a credential).
    """
    try:
        request = request_ctx.get().request
    except LookupError:  # outside any MCP request — nothing to extract
        return ""
    headers = getattr(request, "headers", None)
    if headers is None:
        return ""
    scheme, _, value = str(headers.get("authorization", "")).partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


class _AsgiPassthrough:
    """Adapt the SDK session manager to a Starlette Route endpoint (class => treated as ASGI)."""

    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self._manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._manager.handle_request(scope, receive, send)


def create_app(
    runtime: GatewayRuntime,
    index: dict[str, Any],
    *,
    path: str = _DEFAULT_PATH,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
    metrics: GatewayMetrics | None = None,
    overhead_budget_ms: float = _DEFAULT_BUDGET_MS,
) -> FastAPI:
    """Assemble the FastAPI app: the MCP surface at ``path`` + a ``/healthz`` liveness route.

    DNS-rebinding protection stays ENABLED (ADR-009): Host must match the loopback set (or the
    configured extras) and Origin must be in ``transport.http_allowed_origins`` (empty default =
    browser-originated cross-site requests are refused).
    """
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[*_LOOPBACK_ALLOWED_HOSTS, *(allowed_hosts or [])],
        allowed_origins=list(allowed_origins or []),
    )
    server = build_proxy_server(runtime, index, extract_bearer_token)
    # json_response=True (recorded deviation from the "SDK defaults" line in the M3.1 addendum):
    # the governed proxy is strict request/response — a call returns ONE complete, already-
    # relayed upstream result; nothing is server-pushed mid-call. The SSE streaming mode showed
    # a flaky lost-response race under load (initialize reply dropped between the SSE write and
    # the client reader; reproduced + diagnosed via task-stack dumps this session), while plain
    # JSON responses are deterministic. SSE/resumability can return as a config knob when a
    # feature actually needs server push.
    manager = StreamableHTTPSessionManager(
        app=server, security_settings=security, json_response=True
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with manager.run():  # owns the session task group for the app's whole lifetime
            yield

    app = FastAPI(title="GateKeeperAI gateway", lifespan=lifespan, docs_url=None, redoc_url=None)

    # An exact-path Route (not a Mount): a Mount 307-redirects /mcp -> /mcp/, which not every MCP
    # client follows. Starlette treats a non-function endpoint as a raw ASGI app, which is exactly
    # what the SDK's session manager is. GET=SSE stream, POST=JSON-RPC, DELETE=session terminate.
    app.router.routes.append(
        Route(path, _AsgiPassthrough(manager), methods=["GET", "POST", "DELETE"])
    )

    @app.get("/healthz")
    async def _healthz() -> dict[str, str]:
        # Liveness only (feeds the M3.3 container probe). Deliberately unauthenticated and
        # deliberately empty of config/state — it leaks nothing about the governed surface.
        return {"status": "ok"}

    live_metrics = metrics if metrics is not None else default_metrics

    @app.get("/metrics")
    async def _metrics() -> PlainTextResponse:
        # M3.4 operator surface: Prometheus text exposition (curl-able AND scrapeable).
        # Aggregates only — counts, rates, overhead p95 vs budget; no principals, tools,
        # arguments, or tokens, so liveness-level exposure is acceptable on the loopback/ingress
        # posture (the per-call record stays in the authz-governed ledger).
        return PlainTextResponse(live_metrics.prometheus_text(budget_ms=overhead_budget_ms))

    return app


async def serve_http() -> None:
    """Boot the runtime, enforce the exposure guard, and serve the governed proxy over HTTP."""
    configure_logging(get_settings().log_level)
    log = get_logger("gatekeeper.transport")

    runtime = build_runtime()  # fail-closed HMAC key + fail-loud (ledger table must exist)
    try:
        config = load_config()
        cfg = http_transport_config(config)
        ensure_exposure_acked(cfg["host"], allow_non_loopback=cfg["allow_non_loopback"])
        non_loopback = not _is_loopback(cfg["host"])
        if non_loopback:
            log.warning(
                "serving on a NON-loopback interface: bearer tokens are replayable if "
                "intercepted (ADR-006). Terminate TLS in front of the gateway and prefer "
                "sender-constrained tokens when available.",
                extra={"host": cfg["host"], "port": cfg["port"]},
            )
            # Exposed + the DEV static-token map = the committed demo tokens would grant access
            # off-box (security-review finding). Not a hard refuse (an operator may run their own
            # static map behind a trusted ingress), but it must be a loud, recorded signal —
            # the deploy guide's "switch to OIDC before real use" step exists for exactly this.
            if config["platform"].get("adapters", {}).get("identity") == "static_token":
                log.warning(
                    "exposed bind is using the static_token identity adapter: any caller who "
                    "knows a token in config/identities.yaml gets that role. Switch to "
                    "adapters.identity: oidc for real use (docs/features/oidc-identity.md).",
                    extra={"host": cfg["host"]},
                )

        index = await build_tool_index(runtime)
        log.info(
            "gateway ready",
            extra={
                "transport": "http",
                "bind": f"{cfg['host']}:{cfg['port']}{cfg['path']}",
                "upstreams": runtime.upstream.upstream_names(),
                "tools": sorted(index),
            },
        )
        app = create_app(
            runtime,
            index,
            path=cfg["path"],
            # On an acked non-loopback bind, the configured bind host is also a valid Host
            # header; a hosted deployment adds its public FQDN via http_allowed_hosts.
            allowed_hosts=cfg["allowed_hosts"] + ([f"{cfg['host']}:*"] if non_loopback else []),
            allowed_origins=cfg["allowed_origins"],
            overhead_budget_ms=float(
                config["platform"].get("perf", {}).get("overhead_p95_ms", _DEFAULT_BUDGET_MS)
            ),
        )
        # Single worker BY CONSTRUCTION (ADR-007): the programmatic uvicorn.Server is one
        # process/one event loop; no `workers` knob exists on this path. log_config=None keeps
        # uvicorn from replacing our structured JSON logging; the ledger is the access record.
        server = uvicorn.Server(
            uvicorn.Config(
                app, host=cfg["host"], port=cfg["port"], log_config=None, access_log=False
            )
        )
        await server.serve()
    finally:
        await runtime.aclose()
