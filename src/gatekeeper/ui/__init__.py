"""The approver's and auditor's web UI — served by the gateway, backed by the same ledger DB.

Two ways to run it:
  * ``gatekeeper ui``          a standalone local page (works while an MCP host runs the gateway
                               over stdio: both processes share the ledger database).
  * ``serve --transport http`` mounts the same routes at ``/ui`` next to ``/mcp``.

The UI never bypasses the pipeline: approving here writes the same approval-queue row that
``gatekeeper approve`` writes, and the waiting gateway acts on it exactly the same way.

Access: on a loopback bind the page is open (it is your machine). Beyond loopback it requires
``GATEKEEPER_UI_TOKEN`` (sent as a bearer header; the page stores it locally after you paste it
once) and refuses to mount without one.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from gatekeeper.adapters.approval.sql import ApprovalStateError
from gatekeeper.adapters.ledger.sql import SqlLedgerStore
from gatekeeper.config.loader import ConfigError, get_settings, load_config
from gatekeeper.gateway.factory import open_approvals
from gatekeeper.schemas.enums import ApprovalStatus, Verdict

_PAGE = Path(__file__).with_name("index.html")

#: Ledger rows fetched to build the activity view (calls, not rows, are what the page shows).
ACTIVITY_ROWS = 600


class Decision(BaseModel):
    status: ApprovalStatus = Field(description="approved | denied")
    by: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=500)


def _require_token(request: Request, token: str) -> None:
    if not token:
        return
    supplied = request.headers.get("authorization", "")
    scheme, _, value = supplied.partition(" ")
    if scheme.lower() == "bearer" and value.strip() == token:
        return
    raise HTTPException(status_code=401, detail="UI token required")


def _group_calls(store: SqlLedgerStore, limit: int) -> list[dict[str, Any]]:
    """Newest-first ledger rows -> one record per call: ordered entries + final verdict."""
    rows = store.read(limit=limit)
    calls: dict[str, dict[str, Any]] = {}
    for e in reversed(rows):  # oldest first, so entries stay in seq order
        call = calls.setdefault(
            e.call_id,
            {
                "call_id": e.call_id,
                "ts": e.ts,
                "principal": e.principal,
                "role": e.role,
                "upstream": e.upstream,
                "tool": e.tool,
                "action": e.action_kind.value,
                "final_verdict": e.verdict.value,
                "entries": [],
            },
        )
        call["entries"].append(
            {
                "seq": e.seq,
                "ts": e.ts,
                "verdict": e.verdict.value,
                "reason": e.reason,
                "result": e.result_summary,
            }
        )
        if e.verdict is not Verdict.PENDING:
            call["final_verdict"] = e.verdict.value
        call["last_ts"] = e.ts
    ordered = sorted(calls.values(), key=lambda c: c["last_ts"], reverse=True)
    return ordered


def build_router(open_store: Callable[[], SqlLedgerStore], *, token: str = "") -> APIRouter:
    """The UI routes. ``open_store`` opens a fresh ledger store per request (cross-process safe)."""
    router = APIRouter()

    def guard(request: Request) -> None:
        _require_token(request, token)

    @router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
    async def page() -> str:
        return _PAGE.read_text(encoding="utf-8")

    @router.get("/ui/api/summary")
    async def summary(request: Request) -> dict[str, Any]:
        guard(request)
        store = open_store()
        try:
            calls = _group_calls(store, ACTIVITY_ROWS)
            queue = open_approvals(store)
            try:
                pending = len(queue.list_pending())
            finally:
                queue.close()
            head = store.head()
        finally:
            store.close()
        by_verdict = {"allow": 0, "deny": 0, "pending": 0}
        for c in calls:
            by_verdict[c["final_verdict"]] = by_verdict.get(c["final_verdict"], 0) + 1
        return {"pending": pending, "calls": len(calls), "by_verdict": by_verdict, "head": head}

    @router.get("/ui/api/pending")
    async def pending(request: Request) -> list[dict[str, Any]]:
        guard(request)
        store = open_store()
        try:
            queue = open_approvals(store)
            try:
                return [r.model_dump(mode="json") for r in queue.list_pending()]
            finally:
                queue.close()
        finally:
            store.close()

    @router.post("/ui/api/pending/{request_id}/decision")
    async def decide(request: Request, request_id: str, decision: Decision) -> dict[str, Any]:
        guard(request)
        if decision.status not in (ApprovalStatus.APPROVED, ApprovalStatus.DENIED):
            raise HTTPException(status_code=400, detail="status must be approved or denied")
        store = open_store()
        try:
            queue = open_approvals(store)
            try:
                decided = queue.decide(
                    request_id, decision.status, by=decision.by.strip(), note=decision.note.strip()
                )
            except ApprovalStateError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            finally:
                queue.close()
        finally:
            store.close()
        return decided.model_dump(mode="json")

    @router.get("/ui/api/activity")
    async def activity(request: Request, limit: int = ACTIVITY_ROWS) -> list[dict[str, Any]]:
        guard(request)
        store = open_store()
        try:
            return _group_calls(store, max(1, min(limit, 5000)))
        finally:
            store.close()

    @router.get("/ui/api/calls/{call_id}")
    async def call(request: Request, call_id: str) -> dict[str, Any]:
        guard(request)
        store = open_store()
        try:
            entries, matches = store.lifecycle(call_id)
        finally:
            store.close()
        if matches > 1:
            raise HTTPException(status_code=409, detail="ambiguous id prefix")
        if not entries:
            raise HTTPException(status_code=404, detail="no such call")
        return {
            "call_id": entries[0].call_id,
            "entries": [e.model_dump(mode="json") for e in entries],
        }

    @router.post("/ui/api/verify")
    async def verify(request: Request, expected_head: str | None = None) -> dict[str, Any]:
        guard(request)
        store = open_store()
        try:
            return store.verify(expected_head=expected_head).model_dump(mode="json")
        finally:
            store.close()

    @router.get("/ui/api/servers")
    async def servers(request: Request) -> list[dict[str, Any]]:
        guard(request)
        config = load_config()
        approval = config["product"].get("approval") or {}
        return [
            {
                "name": str(u.get("name")),
                "transport": str(u.get("transport", "stdio")),
                "command": " ".join(str(p) for p in u.get("command", [])) or str(u.get("url", "")),
                "reads": [str(t) for t in u.get("reads", []) or []],
                "writes": [str(t) for t in u.get("writes", []) or []],
                "twin": bool(u.get("demo_twin", False)),
                "of": str(u.get("twin_of", "")),
            }
            for u in config["upstreams"]
        ] + [
            {
                "name": "_policy",
                "approval": {
                    "writes": str(approval.get("writes", "off")),
                    "timeout_s": approval.get("timeout_s", 90),
                    "exempt_roles": approval.get("exempt_roles", []),
                },
            }
        ]

    return router


def create_ui_app(open_store: Callable[[], SqlLedgerStore], *, token: str = "") -> FastAPI:
    """A standalone app for ``gatekeeper ui``."""
    app = FastAPI(title="GateKeeperAI", docs_url=None, redoc_url=None)
    app.include_router(build_router(open_store, token=token))

    @app.get("/", include_in_schema=False)
    async def root() -> HTMLResponse:
        return HTMLResponse(_PAGE.read_text(encoding="utf-8"))

    @app.exception_handler(ConfigError)
    async def _config_error(_request: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    return app


def ui_token_for_bind(host: str) -> str:
    """The token the UI must require for this bind: none on loopback, the configured one beyond."""
    from gatekeeper.transport.http_server import _is_loopback

    if _is_loopback(host):
        return ""
    return get_settings().ui_token
