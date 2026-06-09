"""Integration test — M1.4 "govern ANY server, zero code" against a REAL third-party MCP server.

This is the M1.4 exit-criterion proof. ``mcp-server-time`` is an off-the-shelf MCP server we did
**not** write (the official package, installed via the ``demo`` extra). It is brought under full
governance — identity → RBAC → tamper-evident audit — purely by a ``config/upstreams.yaml`` entry;
there is **no** ``src/gatekeeper/`` change for it. Here we drive a governed call to it through the
real ``GatewayPipeline`` + a real subprocess and assert it is authenticated, RBAC-allowed,
transparently relayed, and recorded in the verifiable ledger.

Skipped (not failed) when the demo extra isn't installed, so the suite still runs lean; CI installs
``.[demo]`` so this proof runs for real on every push.
"""

from __future__ import annotations

import importlib.util
import sys
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
from gatekeeper.gateway.pipeline import GatewayPipeline
from gatekeeper.schemas.enums import ActionKind, Verdict

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mcp_server_time") is None,
    reason="install the demo extra (pip install -e '.[demo]') to govern the third-party server",
)

KEY = "k" * 64  # fake HMAC key — test fixture only, never a real secret
TOKEN = "tok-alice"
_IDENTITIES = [{"token": TOKEN, "principal": "alice", "role": "operator"}]
# Read/write classification comes ONLY from config — exactly how an operator annotates a new server.
ANNOTATIONS = {"time": {"reads": ["get_current_time", "convert_time"], "writes": []}}


def _time_spec() -> UpstreamSpec:
    # Same command shape as config/upstreams.yaml, but sys.executable for a hermetic test run.
    return UpstreamSpec(
        name="time",
        transport="stdio",
        command=(sys.executable, "-m", "mcp_server_time", "--local-timezone", "UTC"),
    )


@pytest.fixture
def ledger(tmp_path: Any) -> Iterator[SqliteLedgerStore]:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    Base.metadata.create_all(engine)
    store = SqliteLedgerStore(Session(engine), KEY)
    yield store
    store.close()


def _pipeline(ledger: SqliteLedgerStore, upstream: McpUpstreamClient) -> GatewayPipeline:
    return GatewayPipeline(
        identity=StaticTokenResolver.from_config(_IDENTITIES),
        classifier=ActionClassifier(
            name_patterns=["write*", "delete*"], upstream_annotations=ANNOTATIONS
        ),
        policy=CedarPolicyEngine.from_config("policies"),  # the SAME committed policy, unchanged
        ledger=ledger,
        upstream=upstream,
        hmac_key=KEY,
    )


async def test_lists_third_party_tools_for_transparent_reexposure() -> None:
    # The gateway discovers the new server's tools (what the transport re-exposes under their
    # original names) — no per-tool wiring, just the config entry.
    upstream = McpUpstreamClient([_time_spec()], timeout=30.0)
    try:
        tools = await upstream.list_tools("time")
        assert {t.name for t in tools} == {"get_current_time", "convert_time"}
    finally:
        await upstream.aclose()


async def test_governs_real_third_party_server_with_zero_code(ledger: SqliteLedgerStore) -> None:
    # The whole point of M1.4: a server we didn't write, governed by config alone.
    upstream = McpUpstreamClient([_time_spec()], timeout=30.0)
    pipe = _pipeline(ledger, upstream)
    try:
        result = await pipe.handle(
            token=TOKEN,
            upstream="time",
            tool="get_current_time",
            arguments={"timezone": "UTC"},
            call_id=uuid.uuid4().hex,
        )

        # Authenticated + RBAC-allowed + TRANSPARENT relay: the agent gets the real server's output.
        assert result.ok
        assert isinstance(result.raw, types.CallToolResult)
        relayed = "".join(b.text for b in result.raw.content if isinstance(b, types.TextContent))
        assert '"timezone": "UTC"' in relayed  # the real server's untouched JSON payload

        # Recorded as a verifiable ALLOW; classified READ purely from config (zero gateway code).
        assert ledger.verify().ok
        entries = ledger.read(limit=10)
        assert len(entries) == 2  # decision-before + outcome-after
        assert all(e.verdict is Verdict.ALLOW for e in entries)
        assert all(e.upstream == "time" and e.tool == "get_current_time" for e in entries)
        assert {e.action_kind for e in entries} == {ActionKind.READ}
        # The Cedar reason names the new server's resource — proof the policy really evaluated it.
        assert any("time::get_current_time" in e.reason for e in entries)
    finally:
        await upstream.aclose()
