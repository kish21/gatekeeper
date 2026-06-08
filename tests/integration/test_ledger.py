"""Integration tests for the SQLite ledger store: chaining, verify, and tamper detection."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.db.base import Base
from gatekeeper.db.models import LedgerEntryRow
from gatekeeper.schemas.enums import ActionKind, Verdict
from gatekeeper.schemas.ledger import GENESIS_HASH, LedgerEntry

KEY = "k" * 64


@pytest.fixture
def store(tmp_path: Any) -> Iterator[SqliteLedgerStore]:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    Base.metadata.create_all(engine)  # schema; the migration is tested separately
    session = Session(engine)
    yield SqliteLedgerStore(session, KEY)
    session.close()


def _entry(call_id: str, **over: Any) -> LedgerEntry:
    base: dict[str, Any] = dict(
        call_id=call_id,
        ts="2026-06-07T17:00:00+00:00",
        principal="alice",
        role="operator",
        upstream="demo",
        tool="read_file",
        action_kind=ActionKind.READ,
        verdict=Verdict.ALLOW,
        reason="ok",
        payload_hash="a" * 64,
    )
    base.update(over)
    return LedgerEntry(**base)


def test_append_chains_entries(store: SqliteLedgerStore):
    e1 = store.append(_entry("c1"))
    e2 = store.append(_entry("c2"))
    assert (e1.seq, e2.seq) == (1, 2)
    assert e1.prev_hash == GENESIS_HASH  # first links to genesis
    assert e2.prev_hash == e1.entry_hash  # chained
    assert e1.entry_hash != e2.entry_hash


def test_verify_ok_on_intact_chain(store: SqliteLedgerStore):
    for i in range(3):
        store.append(_entry(f"c{i}"))
    result = store.verify()
    assert result.ok and result.checked == 3


def test_verify_detects_field_tamper(store: SqliteLedgerStore):
    for i in range(3):
        store.append(_entry(f"c{i}"))
    # Simulate an attacker editing a stored record directly.
    store._session.execute(
        sa.update(LedgerEntryRow).where(LedgerEntryRow.seq == 2).values(reason="HACKED")
    )
    store._session.commit()
    result = store.verify()
    assert not result.ok and result.broken_at == 2


def test_verify_detects_deletion(store: SqliteLedgerStore):
    for i in range(3):
        store.append(_entry(f"c{i}"))
    store._session.execute(sa.delete(LedgerEntryRow).where(LedgerEntryRow.seq == 2))
    store._session.commit()
    result = store.verify()
    assert not result.ok and result.broken_at == 3  # entry 3's prev_hash no longer links


def test_wrong_key_cannot_verify(store: SqliteLedgerStore):
    store.append(_entry("c1"))
    forger = SqliteLedgerStore(store._session, "z" * 64)  # same data, wrong key
    result = forger.verify()
    assert not result.ok and result.broken_at == 1


def test_read_get_and_tenant_filter(store: SqliteLedgerStore):
    store.append(_entry("c1", principal="alice"))
    store.append(_entry("c2", principal="bob"))
    assert len(store.read(limit=10)) == 2
    assert [e.principal for e in store.read(principal="alice")] == ["alice"]
    got = store.get("c2")
    assert got is not None and got.principal == "bob"
    assert store.get("missing") is None
