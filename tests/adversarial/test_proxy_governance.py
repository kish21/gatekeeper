"""Adversarial tests — try to bypass governance or hide a forwarded call, against a REAL ledger.

The north-star is "no call slips past, all provable". These prove it holds under attack:
  * an unauthenticated token can never reach the upstream (fail-closed) yet is still recorded,
  * a ledger that refuses the pre-forward write blocks the forward (no un-audited side effect),
  * the proxy's own audit trail is tamper-evident — editing a recorded result breaks ``verify``.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from gatekeeper.adapters.identity.static_token import StaticTokenResolver
from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.db.base import Base
from gatekeeper.db.models import LedgerEntryRow
from gatekeeper.domain.classify import ActionClassifier
from gatekeeper.domain.errors import IdentityError
from gatekeeper.gateway.pipeline import UNAUTHENTICATED_PRINCIPAL, GatewayPipeline
from gatekeeper.schemas.enums import Verdict
from gatekeeper.schemas.ledger import LedgerEntry, VerifyResult
from gatekeeper.schemas.models import ToolCall, ToolResult

KEY = "k" * 64


class SpyUpstream:
    """Records whether forward was ever reached (it must NOT be, on a blocked call)."""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def forward(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        return ToolResult(call_id=call.call_id, ok=True, summary="forwarded")


class RefusingLedger:
    """A ledger that refuses every append (simulates the audit store being unavailable)."""

    def append(self, entry: LedgerEntry) -> LedgerEntry:
        raise RuntimeError("ledger write refused")

    def read(self, *, limit: int = 100, principal: str | None = None) -> Sequence[LedgerEntry]:
        raise NotImplementedError

    def get(self, call_id: str) -> LedgerEntry | None:
        raise NotImplementedError

    def verify(self) -> VerifyResult:
        raise NotImplementedError


@pytest.fixture
def store(tmp_path: Any) -> Iterator[SqliteLedgerStore]:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield SqliteLedgerStore(session, KEY)
    session.close()


def _pipeline(ledger: Any, upstream: Any) -> GatewayPipeline:
    return GatewayPipeline(
        identity=StaticTokenResolver.from_config(
            [{"token": "good", "principal": "alice", "role": "operator"}]
        ),
        classifier=ActionClassifier(name_patterns=["write*"], upstream_annotations={}),
        ledger=ledger,
        upstream=upstream,
        hmac_key=KEY,
    )


async def test_unauthenticated_call_is_denied_recorded_and_never_forwarded(
    store: SqliteLedgerStore,
) -> None:
    spy = SpyUpstream()
    pipe = _pipeline(store, spy)
    with pytest.raises(IdentityError):
        await pipe.handle(
            token="stolen", upstream="demo", tool="write_file", arguments={"x": 1}, call_id="c1"
        )
    assert spy.calls == []  # the forbidden call never reached the upstream
    recorded = store.read(limit=10)
    assert len(recorded) == 1 and recorded[0].verdict is Verdict.DENY
    assert recorded[0].principal == UNAUTHENTICATED_PRINCIPAL
    assert store.verify().ok  # the deny is itself in the tamper-evident chain


async def test_audit_store_failure_blocks_the_forward() -> None:
    spy = SpyUpstream()
    pipe = _pipeline(RefusingLedger(), spy)
    with pytest.raises(RuntimeError, match="refused"):
        await pipe.handle(
            token="good", upstream="demo", tool="write_file", arguments={}, call_id="c2"
        )
    assert spy.calls == []  # audit-before-act: a failed audit means NO side effect


async def test_tampering_with_a_recorded_result_breaks_verify(store: SqliteLedgerStore) -> None:
    spy = SpyUpstream()
    pipe = _pipeline(store, spy)
    await pipe.handle(token="good", upstream="demo", tool="write_file", arguments={}, call_id="c3")
    assert store.verify().ok

    # Attacker edits a recorded result_summary directly in the DB (bypassing append).
    store._session.execute(
        sa.update(LedgerEntryRow).where(LedgerEntryRow.seq == 2).values(result_summary="TAMPERED")
    )
    store._session.commit()

    result = store.verify()
    assert not result.ok and result.broken_at == 2
