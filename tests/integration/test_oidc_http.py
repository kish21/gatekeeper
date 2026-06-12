"""Integration — REAL RS256 JWTs over the LIVE HTTP transport (M3.2 x M3.1).

The M3 exit shape end-to-end: a network MCP client authenticates with an IdP-style JWT in
``Authorization: Bearer``; the per-request seam (ADR-008) hands it to the OIDC resolver inside
the pipeline; group->role mapping authorizes it; everything lands in the ledger verify-clean.
Only the JWKS fetch is stubbed (the fake IdP's public key) — signature/audience/expiry
validation, transport, pipeline, Cedar, and ledger are all real (plumbing: ``http_harness``).
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from tests.integration.http_harness import client, serving, text
from tests.unit.test_identity_oidc import (
    AUDIENCE,
    GROUP_OPS,
    GROUP_RO,
    ISSUER,
    ROLE_MAP,
    StubJwks,
    _token,
)

from gatekeeper.adapters.identity.oidc import OidcIdentityResolver
from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.adapters.policy.cedar import CedarPolicyEngine
from gatekeeper.adapters.upstream.mcp_client import McpUpstreamClient, UpstreamSpec
from gatekeeper.db.base import Base
from gatekeeper.domain.classify import ActionClassifier
from gatekeeper.gateway.factory import GatewayRuntime
from gatekeeper.gateway.pipeline import UNAUTHENTICATED_PRINCIPAL, GatewayPipeline
from gatekeeper.schemas.enums import Verdict

KEY = "k" * 64
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


def _oidc_runtime(ledger: SqliteLedgerStore) -> GatewayRuntime:
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
    identity = OidcIdentityResolver(
        issuer=ISSUER, audience=AUDIENCE, group_role_map=ROLE_MAP, jwks_client=StubJwks()
    )
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


async def test_oidc_jwt_over_http_governs_and_ledgers(ledger: SqliteLedgerStore) -> None:
    fname = f"oidc-{uuid.uuid4().hex}.txt"
    async with serving(_oidc_runtime(ledger)) as base:
        # Operator-group JWT: authenticated by signature/aud/exp, authorized by group->role map.
        async with client(base, _token(sub="alice@example.test")) as alice:
            write = await alice.call_tool("write_file", {"path": fname, "content": "via-oidc"})
            assert not write.isError

        # Readonly-group JWT: REAL token, valid signature — but Cedar denies the write.
        async with client(base, _token(sub="bob@example.test", groups=[GROUP_RO])) as bob:
            denied = await bob.call_tool("write_file", {"path": fname, "content": "nope"})
            assert denied.isError and "denied" in text(denied)

        # Expired JWT: identity-deny, LEDGERED as <unauthenticated> (never silently dropped).
        expired = _token(sub="alice@example.test", exp=1)
        async with client(base, expired) as stale:
            result = await stale.call_tool("read_file", {"path": fname})
            assert result.isError and "denied" in text(result)

    entries = ledger.read(limit=20)
    by_verdict = {(e.principal, e.verdict) for e in entries}
    assert ("alice@example.test", Verdict.ALLOW) in by_verdict  # JWT subject IS the principal
    assert ("bob@example.test", Verdict.DENY) in by_verdict
    assert (UNAUTHENTICATED_PRINCIPAL, Verdict.DENY) in by_verdict
    assert ledger.verify().ok
    # The raw JWTs are credentials: none may appear anywhere in the ledger.
    assert all(expired not in e.model_dump_json() for e in entries)


async def test_oidc_group_membership_changes_role_not_code(ledger: SqliteLedgerStore) -> None:
    # Same person, different IdP group claims -> different governed role, zero gateway change:
    # exactly the "plug in the company IdP" outcome from the M3.2 scope row.
    async with serving(_oidc_runtime(ledger)) as base:
        async with client(base, _token(sub="carol@example.test", groups=[GROUP_OPS])) as ops:
            ok = await ops.call_tool("list_dir", {"path": "."})
            assert not ok.isError
        async with client(base, _token(sub="carol@example.test", groups=["not-mapped"])) as none:
            refused = await none.call_tool("list_dir", {"path": "."})
            assert refused.isError and "denied" in text(refused)
    assert ledger.verify().ok
