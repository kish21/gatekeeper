"""Integration — the ledger on a REAL PostgreSQL database: durable, and safe with many writers.

This is the deployment shape the hosted gateway needs and the SQLite file could not provide: the
audit trail lives in a managed database, so it survives the container being replaced, a second
process can read it while the gateway writes, and more than one replica can serve at once.

The tests here run only when ``GATEKEEPER_TEST_POSTGRES_URL`` points at a database they may create
tables in (CI starts one as a service; locally, any throwaway Postgres works). Without it they
skip — the SQLite tests still cover the same store, since it is one implementation over both.

What each test pins down:
  * a fresh database is migrated on open, and append/read/get/head/verify behave as on SQLite;
  * entries written by one process are read back by a NEW process against a NEW connection — the
    "records survived a restart" property that Azure Files/SMB silently broke;
  * six concurrent processes appending at once produce ONE intact chain (the advisory lock in
    ``db.base.lock_chain`` is what makes this true — ``test_chain_lock`` proves it is issued);
  * two approvers deciding the same held write at the same moment: one wins, one is refused.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from gatekeeper.adapters.approval.sql import ApprovalStateError, SqlApprovalQueue
from gatekeeper.adapters.ledger.factory import migrate, open_ledger
from gatekeeper.adapters.ledger.sql import SqlLedgerStore
from gatekeeper.db.base import create_ledger_engine
from gatekeeper.schemas.approval import ApprovalRequest
from gatekeeper.schemas.enums import ActionKind, ApprovalStatus, Verdict
from gatekeeper.schemas.ledger import LedgerEntry

KEY = "p" * 64
#: Writers x appends each for the concurrency test. Six is more replicas than a hosted gateway
#: usually runs, on purpose: the chain must hold with room to spare.
WRITERS, PER_WRITER = 6, 20

pytestmark = pytest.mark.skipif(
    not os.environ.get("GATEKEEPER_TEST_POSTGRES_URL"),
    reason="set GATEKEEPER_TEST_POSTGRES_URL to a throwaway Postgres for the durable-ledger tests",
)


def _entry(call_id: str, principal: str = "alice") -> LedgerEntry:
    return LedgerEntry(
        call_id=call_id,
        ts="2026-09-08T10:00:00+00:00",
        principal=principal,
        role="operator",
        upstream="demo",
        tool="write_file",
        action_kind=ActionKind.WRITE,
        verdict=Verdict.ALLOW,
        reason=f"entry {call_id}",
        payload_hash="a" * 64,
    )


@pytest.fixture
def pg_url() -> str:
    """A migrated, EMPTY ledger schema in the test database (each test gets a clean chain)."""
    url = os.environ["GATEKEEPER_TEST_POSTGRES_URL"]
    migrate(url)
    engine = create_ledger_engine(url)
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE ledger_entry, approval_request RESTART IDENTITY"))
    engine.dispose()
    return url


def _store(url: str) -> SqlLedgerStore:
    return SqlLedgerStore(Session(create_ledger_engine(url)), KEY)


def test_append_read_verify_on_postgres(pg_url: str) -> None:
    store = _store(pg_url)
    try:
        first = store.append(_entry("call-1"))
        second = store.append(_entry("call-2"))

        assert (first.seq, second.seq) == (1, 2)
        assert second.prev_hash == first.entry_hash
        assert [e.call_id for e in store.read(limit=10)] == ["call-2", "call-1"]
        assert store.get("call-1") is not None
        assert store.head() == second.entry_hash

        result = store.verify(expected_head=second.entry_hash)
        assert (result.ok, result.checked) == (True, 2)
    finally:
        store.close()


def test_records_survive_the_process_that_wrote_them(pg_url: str) -> None:
    """The Azure defect, inverted: a NEW process on a NEW connection still sees the chain.

    On Azure Files/SMB the file read back as zero bytes from a second process and lost every
    record across a restart. Against Postgres the data is in the database, not in a file the
    container owns, so a replaced replica reads exactly what the previous one committed.
    """
    writer = _store(pg_url)
    try:
        for i in range(5):
            writer.append(_entry(f"before-restart-{i}"))
        head = writer.head()
    finally:
        writer.close()  # the "container was replaced" moment: connection gone, data stays

    reader = _store(pg_url)
    try:
        assert len(reader.read(limit=50)) == 5
        assert reader.verify(expected_head=head).ok is True
    finally:
        reader.close()


def _append_batch(url: str, who: str, count: int) -> None:
    """Run in a separate PROCESS: a replica of the gateway appending to the shared ledger."""
    store = SqlLedgerStore(Session(create_ledger_engine(url)), KEY)
    try:
        for i in range(count):
            store.append(_entry(f"{who}-{i}", principal=who))
    finally:
        store.close()


def test_concurrent_replicas_produce_one_intact_chain(pg_url: str) -> None:
    """Many gateway replicas append at once; the hash chain stays single and verifiable.

    Without the advisory lock two writers read the same head and both chain onto it, which
    ``verify`` reports as broken linkage. With it, every append is serialized at the database.
    """
    ctx = mp.get_context("spawn")
    workers = [
        ctx.Process(target=_append_batch, args=(pg_url, f"replica{n}", PER_WRITER))
        for n in range(WRITERS)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=120)

    assert [w.exitcode for w in workers] == [0] * WRITERS

    store = _store(pg_url)
    try:
        result = store.verify()
        assert result.ok is True, result.detail
        assert result.checked == WRITERS * PER_WRITER
    finally:
        store.close()


def _decide(url: str, request_id: str, who: str, outcome: mp.Queue) -> None:  # type: ignore[type-arg]
    """Run in a separate PROCESS: one approver deciding a held write."""
    queue = SqlApprovalQueue(Session(create_ledger_engine(url)))
    try:
        queue.decide(request_id, ApprovalStatus.APPROVED, by=who)
        outcome.put(("won", who))
    except ApprovalStateError as exc:
        outcome.put(("refused", str(exc)))
    finally:
        queue.close()


def test_two_approvers_racing_one_request(pg_url: str) -> None:
    """A decision cannot be made twice, even by two people clicking at the same instant."""
    request_id = uuid.uuid4().hex[:8]
    queue = SqlApprovalQueue(Session(create_ledger_engine(pg_url)))
    queue.create(
        ApprovalRequest(
            id=request_id,
            call_id="call-race",
            ts="2026-09-08T10:00:00+00:00",
            principal="alice",
            role="operator",
            upstream="demo",
            tool="write_file",
            arguments_preview="{}",
        )
    )

    ctx = mp.get_context("spawn")
    results: mp.Queue = ctx.Queue()  # type: ignore[type-arg]
    racers = [
        ctx.Process(target=_decide, args=(pg_url, request_id, who, results))
        for who in ("priya", "sam")
    ]
    for racer in racers:
        racer.start()
    for racer in racers:
        racer.join(timeout=60)

    outcomes = sorted(results.get(timeout=10)[0] for _ in racers)
    assert outcomes == ["refused", "won"]
    assert queue.get(request_id).status is ApprovalStatus.APPROVED  # type: ignore[union-attr]
    queue.close()


def test_open_ledger_uses_the_configured_url(pg_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """GATEKEEPER_LEDGER_URL alone moves the whole gateway onto Postgres — no code path chosen."""
    from gatekeeper.config import loader

    monkeypatch.setenv("GATEKEEPER_LEDGER_URL", pg_url)
    monkeypatch.setenv("GATEKEEPER_HMAC_KEY", KEY)
    loader.get_settings.cache_clear()
    try:
        store = open_ledger()
        try:
            assert store.engine.dialect.name == "postgresql"
            assert store.append(_entry("via-config")).seq == 1
        finally:
            store.close()
    finally:
        loader.get_settings.cache_clear()
