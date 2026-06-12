"""Integration — the LIVE Streamable HTTP path (M3.1): real uvicorn, real MCP client, real ledger.

Boots the governed FastAPI app on an ephemeral loopback port and drives it with the official MCP
client over genuine HTTP (shared plumbing: ``http_harness``). Proves the M3.1 exit criterion:
calls over HTTP run the SAME pipeline (transparent result, RBAC deny, identity-deny all LEDGERED)
and the chain stays `verify`-clean; plus the ADR-008 fail-closed surface (no unauthenticated tool
enumeration) and the ADR-009 DNS-rebinding protection (bad Host header refused).
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from tests.integration.http_harness import client, serving, text

from gatekeeper.adapters.identity.static_token import StaticTokenResolver
from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.adapters.policy.cedar import CedarPolicyEngine
from gatekeeper.adapters.upstream.mcp_client import McpUpstreamClient, UpstreamSpec
from gatekeeper.db.base import Base
from gatekeeper.domain.classify import ActionClassifier
from gatekeeper.gateway.factory import GatewayRuntime
from gatekeeper.gateway.pipeline import UNAUTHENTICATED_PRINCIPAL, GatewayPipeline
from gatekeeper.schemas.enums import Verdict

KEY = "k" * 64
TOKEN = "tok-alice"
RO_TOKEN = "tok-bob"
_IDENTITIES = [
    {"token": TOKEN, "principal": "alice", "role": "operator"},
    {"token": RO_TOKEN, "principal": "bob", "role": "readonly"},
]
ANNOTATIONS = {
    "demo-files": {"writes": ["write_file", "delete_file"], "reads": ["read_file", "list_dir"]}
}


@pytest.fixture
def ledger(tmp_path: Any) -> Iterator[SqliteLedgerStore]:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    store = SqliteLedgerStore(session, KEY)
    yield store
    store.close()


def _runtime(ledger: SqliteLedgerStore) -> GatewayRuntime:
    upstream = McpUpstreamClient(
        [
            UpstreamSpec(
                name="demo-files",
                transport="stdio",
                command=(sys.executable, "-m", "examples.demo_file_server"),
            )
        ],
        timeout=30.0,
    )
    identity = StaticTokenResolver.from_config(_IDENTITIES)
    pipeline = GatewayPipeline(
        identity=identity,
        classifier=ActionClassifier(
            name_patterns=["write*", "delete*"], upstream_annotations=ANNOTATIONS
        ),
        policy=CedarPolicyEngine.from_config("policies"),
        ledger=ledger,
        upstream=upstream,
        hmac_key=KEY,
    )
    return GatewayRuntime(pipeline=pipeline, identity=identity, upstream=upstream, ledger=ledger)


async def test_http_calls_run_the_same_pipeline_and_verify_clean(
    ledger: SqliteLedgerStore,
) -> None:
    fname = f"http-{uuid.uuid4().hex}.txt"
    async with serving(_runtime(ledger)) as base:
        # Two principals over ONE gateway process — the per-request bearer model (ADR-008),
        # impossible over stdio (one token per process).
        async with client(base, TOKEN) as alice:
            tools = await alice.list_tools()
            assert {"read_file", "write_file"} <= {t.name for t in tools.tools}

            write = await alice.call_tool(
                "write_file", {"path": fname, "content": "hello-over-http"}
            )
            assert not write.isError
            read = await alice.call_tool("read_file", {"path": fname})
            assert not read.isError
            assert "hello-over-http" in text(read)  # transparent relay over HTTP

        async with client(base, RO_TOKEN) as bob:
            denied = await bob.call_tool("write_file", {"path": fname, "content": "nope"})
            assert denied.isError and "denied" in text(denied)  # RBAC deny surfaces as an error

        # /healthz liveness (M3.3 container probe) — unauthenticated, leaks nothing.
        async with httpx.AsyncClient() as http:
            health = await http.get(f"{base}/healthz")
            assert health.status_code == 200 and health.json() == {"status": "ok"}
            # /metrics (M3.4): live counters + overhead p95 vs budget, aggregates only —
            # no principal, tool argument, or token may appear.
            metrics = (await http.get(f"{base}/metrics")).text
            assert 'gatekeeper_calls_total{verdict="allow"}' in metrics
            assert "gatekeeper_overhead_p95_ms" in metrics
            assert "gatekeeper_overhead_budget_ms" in metrics
            assert "alice" not in metrics and TOKEN not in metrics

    # Every HTTP call was LEDGERED through the identical pipeline and the chain verifies.
    assert ledger.verify().ok
    entries = ledger.read(limit=20)
    assert len(entries) == 5  # 2 allowed calls x2 (decision+outcome) + 1 deny decision
    denies = [e for e in entries if e.verdict is Verdict.DENY]
    assert len(denies) == 1 and denies[0].principal == "bob"
    assert all("hello-over-http" not in e.model_dump_json() for e in entries)  # PII stance holds


async def test_http_unauthenticated_is_fail_closed_and_ledgered(
    ledger: SqliteLedgerStore,
) -> None:
    async with serving(_runtime(ledger)) as base:
        # No bearer at all: tool enumeration yields NOTHING (ADR-008 — fail-closed; an empty
        # list rather than an error so the SDK's internal tools/list refresh during a
        # tools/call can never short-circuit the pipeline's ledgered identity-deny).
        async with client(base, None) as anon:
            listed = await anon.list_tools()
            assert listed.tools == []

        # A FORGED bearer on tools/call still reaches the pipeline, which ledgers the
        # identity-deny and then refuses — never a silent transport-level 401.
        async with client(base, "tok-forged") as intruder:
            result = await intruder.call_tool("read_file", {"path": "x.txt"})
            assert result.isError and "denied" in text(result)

            # No tool-enumeration oracle (security-review hardening): a REAL tool and a
            # nonexistent tool both return the SAME generic "denied" to an unauthenticated
            # caller — "unknown tool" must NOT leak which names are proxied.
            real = await intruder.call_tool("read_file", {"path": "x"})
            bogus = await intruder.call_tool("no_such_tool_xyz", {})
            assert text(real) == text(bogus)
            assert "unknown tool" not in text(bogus)

    entries = ledger.read(limit=10)
    # Every identity-deny on a tools/call is ledgered (the read_file probes reach the pipeline);
    # the bogus-name probe is refused pre-routing with the same generic message.
    assert entries and all(e.principal == UNAUTHENTICATED_PRINCIPAL for e in entries)
    assert all(e.verdict is Verdict.DENY for e in entries)
    assert ledger.verify().ok


async def test_http_rejects_unknown_host_header(ledger: SqliteLedgerStore) -> None:
    # ADR-009: SDK DNS-rebinding protection stays ON — a rebound Host is refused at the door.
    async with serving(_runtime(ledger)) as base:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{base}/mcp",
                headers={"Host": "evil.example", "Content-Type": "application/json"},
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            )
            assert resp.status_code == 421
    assert ledger.read(limit=5) == []  # never reached the surface, nothing to govern
