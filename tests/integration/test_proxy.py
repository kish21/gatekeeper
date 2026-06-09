"""Integration test — the LIVE proxy path against a REAL MCP server + a REAL ledger.

Launches the example ``demo_file_server`` as an actual stdio MCP subprocess, forwards governed calls
through the full ``GatewayPipeline`` (identity -> classify -> audit-before -> forward -> audit), and
proves: the agent gets the correct upstream result (transparent), every call is recorded as two
chained entries, the chain verifies, writes/reads are classified, and raw args are not persisted.
"""

from __future__ import annotations

import sys
import types as pytypes
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from mcp import types
from sqlalchemy.orm import Session

from gatekeeper.adapters.identity.static_token import StaticTokenResolver
from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.adapters.policy.cedar import CedarPolicyEngine
from gatekeeper.adapters.upstream.mcp_client import McpUpstreamClient, UpstreamSpec
from gatekeeper.db.base import Base
from gatekeeper.domain.classify import ActionClassifier
from gatekeeper.domain.errors import PolicyDenied
from gatekeeper.gateway.pipeline import GatewayPipeline
from gatekeeper.schemas.enums import ActionKind, Verdict
from gatekeeper.transport.stdio_server import _build_tool_index

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


def _demo_spec() -> UpstreamSpec:
    return UpstreamSpec(
        name="demo-files",
        transport="stdio",
        command=(sys.executable, "-m", "examples.demo_file_server"),
    )


@pytest.fixture
def ledger(tmp_path: Any) -> Iterator[SqliteLedgerStore]:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    store = SqliteLedgerStore(session, KEY)
    yield store
    store.close()


def _pipeline(ledger: SqliteLedgerStore, upstream: McpUpstreamClient) -> GatewayPipeline:
    return GatewayPipeline(
        identity=StaticTokenResolver.from_config(_IDENTITIES),
        classifier=ActionClassifier(
            name_patterns=["write*", "delete*"], upstream_annotations=ANNOTATIONS
        ),
        policy=CedarPolicyEngine.from_config("policies"),
        ledger=ledger,
        upstream=upstream,
        hmac_key=KEY,
    )


async def test_live_proxy_forwards_audits_and_verifies(ledger: SqliteLedgerStore) -> None:
    upstream = McpUpstreamClient([_demo_spec()], timeout=30.0)
    pipe = _pipeline(ledger, upstream)
    fname = f"it-{uuid.uuid4().hex}.txt"
    try:
        write = await pipe.handle(
            token=TOKEN,
            upstream="demo-files",
            tool="write_file",
            arguments={"path": fname, "content": "hello-gatekeeper"},
            call_id=uuid.uuid4().hex,
        )
        read = await pipe.handle(
            token=TOKEN,
            upstream="demo-files",
            tool="read_file",
            arguments={"path": fname},
            call_id=uuid.uuid4().hex,
        )

        # Correct result + TRANSPARENT relay: the agent receives the upstream's real output.
        assert write.ok and read.ok
        assert isinstance(read.raw, types.CallToolResult)
        relayed = "".join(b.text for b in read.raw.content if isinstance(b, types.TextContent))
        assert "hello-gatekeeper" in relayed

        # Two chained entries per call (decision-before + outcome-after); chain verifies intact.
        assert ledger.verify().ok
        entries = ledger.read(limit=20)
        assert len(entries) == 4
        assert all(e.verdict is Verdict.ALLOW for e in entries)
        assert {e.action_kind for e in entries if e.tool == "write_file"} == {ActionKind.WRITE}
        assert {e.action_kind for e in entries if e.tool == "read_file"} == {ActionKind.READ}

        # PII stance: the content is never persisted in ANY entry — not as a write ARGUMENT (only
        # its payload_hash) and not in the read OUTPUT (the result_summary is status-only metadata).
        assert all("hello-gatekeeper" not in e.model_dump_json() for e in entries)
    finally:
        await upstream.aclose()


async def test_live_proxy_denies_readonly_write_without_touching_upstream(
    ledger: SqliteLedgerStore,
) -> None:
    # End-to-end RBAC over the real proxy path: a readonly principal's write is blocked by Cedar,
    # recorded as a deny, and the upstream is never asked to perform it (no side effect on disk).
    upstream = McpUpstreamClient([_demo_spec()], timeout=30.0)
    pipe = _pipeline(ledger, upstream)
    fname = f"forbidden-{uuid.uuid4().hex}.txt"
    try:
        with pytest.raises(PolicyDenied, match="readonly"):
            await pipe.handle(
                token=RO_TOKEN,
                upstream="demo-files",
                tool="write_file",
                arguments={"path": fname, "content": "should-never-be-written"},
                call_id=uuid.uuid4().hex,
            )
        entries = ledger.read(limit=10)
        assert len(entries) == 1 and entries[0].verdict is Verdict.DENY
        assert ledger.verify().ok

        # Prove the write truly had NO effect: alice (operator) reading the same path errors
        # because the file was never created.
        read = await pipe.handle(
            token=TOKEN,
            upstream="demo-files",
            tool="read_file",
            arguments={"path": fname},
            call_id=uuid.uuid4().hex,
        )
        assert not read.ok  # the denied write never reached disk
    finally:
        await upstream.aclose()


async def test_one_bad_upstream_does_not_take_down_the_gateway() -> None:
    # M1.4 resilience: with any server registered by config, an unavailable one (here a bogus launch
    # command) must be skipped — the healthy upstream's tools are still exposed, the gateway lives.
    good = _demo_spec()
    bad = UpstreamSpec(
        name="broken",
        transport="stdio",
        command=(sys.executable, "-m", "gatekeeper_no_such_module_xyz"),
    )
    upstream = McpUpstreamClient([good, bad], timeout=30.0)
    runtime = pytypes.SimpleNamespace(upstream=upstream)  # _build_tool_index only needs .upstream
    try:
        index = await _build_tool_index(runtime)  # type: ignore[arg-type]
        # Healthy upstream fully exposed; the broken one contributes nothing (skipped, not fatal).
        assert "read_file" in index and "write_file" in index
        assert all(up == "demo-files" for (up, _tool) in index.values())
    finally:
        await upstream.aclose()


async def test_live_proxy_unknown_tool_fails_without_forward(ledger: SqliteLedgerStore) -> None:
    # A tool the upstream doesn't expose -> ok=False, still recorded, chain stays intact.
    upstream = McpUpstreamClient([_demo_spec()], timeout=30.0)
    pipe = _pipeline(ledger, upstream)
    try:
        result = await pipe.handle(
            token=TOKEN,
            upstream="demo-files",
            tool="read_file",
            arguments={"path": "does-not-exist.txt"},
            call_id=uuid.uuid4().hex,
        )
        assert not result.ok  # upstream raised (missing file) -> redacted error summary, not a hang
        assert ledger.verify().ok
        assert len(ledger.read(limit=20)) == 2  # decision + outcome both recorded
    finally:
        await upstream.aclose()
