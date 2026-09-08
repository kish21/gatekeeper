"""Unit — operating an audit ledger for years without giving up what makes it worth having.

Three things a real deployment needs, each of which naively breaks the hash chain:

  * **Export.** The SIEM wants the records in a shape it can ingest. Copying them out must not
    change anything, and must not cost memory proportional to the ledger.
  * **Retention.** A chain proves nothing was removed; a retention policy exists to remove things.
    The resolution is a *signed checkpoint*: a prune records where the cut was and what the chain
    stood at, signed with the ledger key, and `verify` resumes from it. Removing records without
    such an account still reads as tampering — that is the test that matters here.
  * **Key rotation.** Rotating the chain key used to orphan every existing record, which in
    practice means nobody rotates. Entries now name the key that signed them, so one `verify`
    walks straight through a rotation — and says so clearly if a retired key was thrown away.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from gatekeeper.adapters.ledger.factory import migrate
from gatekeeper.adapters.ledger.hashchain import key_fingerprint
from gatekeeper.adapters.ledger.sql import SqlLedgerStore
from gatekeeper.db.base import create_ledger_engine
from gatekeeper.schemas.enums import ActionKind, Verdict
from gatekeeper.schemas.ledger import LedgerEntry

OLD_KEY = "o" * 64
NEW_KEY = "n" * 64


def _entry(i: int, *, month: int) -> LedgerEntry:
    return LedgerEntry(
        call_id=f"call-{i}",
        ts=f"2026-{month:02d}-01T09:0{i}:00+00:00",
        principal="alice",
        role="operator",
        upstream="github",
        tool="create_issue",
        action_kind=ActionKind.WRITE,
        verdict=Verdict.ALLOW,
        reason=f"entry {i}",
        payload_hash="a" * 64,
    )


@pytest.fixture
def ledger(tmp_path: Path) -> tuple[SqlLedgerStore, str]:
    """Six entries: three in January, three in September."""
    db = str(tmp_path / "audit.db")
    migrate(db)
    store = SqlLedgerStore(Session(create_ledger_engine(db)), OLD_KEY)
    for i in range(3):
        store.append(_entry(i, month=1))
    for i in range(3, 6):
        store.append(_entry(i, month=9))
    return store, db


# --- export -------------------------------------------------------------------------------------


def test_export_streams_a_window_oldest_first(ledger: tuple[SqlLedgerStore, str]) -> None:
    store, _ = ledger
    january = list(store.entries_between(until_ts="2026-06-01"))
    september = list(store.entries_between(since_ts="2026-06-01"))

    assert [e.seq for e in january] == [1, 2, 3]
    assert [e.seq for e in september] == [4, 5, 6]
    assert list(store.entries_between()) == [*january, *september]


def test_export_pages_through_a_ledger_larger_than_one_batch(
    ledger: tuple[SqlLedgerStore, str],
) -> None:
    """Bounded memory: a year of records must not be loaded at once to be written out."""
    store, _ = ledger
    assert [e.seq for e in store.entries_between(batch=2)] == [1, 2, 3, 4, 5, 6]


def test_exporting_changes_nothing(ledger: tuple[SqlLedgerStore, str]) -> None:
    store, _ = ledger
    head_before = store.head()
    list(store.entries_between())
    assert store.head() == head_before
    assert store.verify().ok is True


# --- retention ----------------------------------------------------------------------------------


def test_a_prune_leaves_a_verifiable_chain_and_says_what_it_removed(
    ledger: tuple[SqlLedgerStore, str],
) -> None:
    store, _ = ledger
    head_before = store.head()

    checkpoint = store.prune_before(
        "2026-06-01", archive_path="/tmp/2026h1.jsonl", note="retention: 6 months"
    )

    assert (checkpoint.through_seq, checkpoint.pruned_count) == (3, 3)
    result = store.verify()
    assert result.ok is True, result.detail
    assert result.checked == 3  # only what is left is walked
    assert result.head == head_before  # the head is unchanged: a pinned head still matches
    assert result.checkpoint is not None
    assert "retention checkpoint" in result.detail
    assert result.checkpoint.archive_path == "/tmp/2026h1.jsonl"


def test_removing_records_without_a_checkpoint_is_still_tampering(
    ledger: tuple[SqlLedgerStore, str],
) -> None:
    """The loophole this design exists to close: retention must not become a way to erase."""
    store, db = ledger
    connection = sqlite3.connect(db)
    connection.execute("DELETE FROM ledger_entry WHERE seq <= 2")
    connection.commit()
    connection.close()

    result = store.verify()
    assert result.ok is False
    assert "linkage broken" in result.detail


def test_a_forged_or_edited_checkpoint_is_caught(ledger: tuple[SqlLedgerStore, str]) -> None:
    """Rewriting the account of a deletion must fail as loudly as the deletion itself."""
    store, db = ledger
    store.prune_before("2026-06-01", archive_path="/tmp/a.jsonl")

    connection = sqlite3.connect(db)
    connection.execute("UPDATE ledger_checkpoint SET pruned_count = 1, note = 'routine'")
    connection.commit()
    connection.close()

    result = store.verify()
    assert result.ok is False
    assert "altered or forged" in result.detail


def test_an_invented_checkpoint_cannot_hide_a_deletion(ledger: tuple[SqlLedgerStore, str]) -> None:
    """Someone deletes records and writes their own checkpoint. They do not have the key."""
    store, db = ledger
    entries = list(store.entries_between())
    connection = sqlite3.connect(db)
    connection.execute("DELETE FROM ledger_entry WHERE seq <= 3")
    connection.execute(
        "INSERT INTO ledger_checkpoint "
        "(created_at, through_seq, through_hash, pruned_count, archive_path, note, key_id,"
        " checkpoint_hash) VALUES (?, ?, ?, ?, '', 'housekeeping', ?, ?)",
        (
            "2026-09-08T00:00:00+00:00",
            3,
            entries[2].entry_hash,
            3,
            key_fingerprint(OLD_KEY),
            "0" * 64,  # a hash they cannot compute without the key
        ),
    )
    connection.commit()
    connection.close()

    result = store.verify()
    assert result.ok is False
    assert "altered or forged" in result.detail


def test_pruning_nothing_is_refused_rather_than_recorded(
    ledger: tuple[SqlLedgerStore, str],
) -> None:
    store, _ = ledger
    with pytest.raises(ValueError, match="nothing in the ledger is older"):
        store.prune_before("2020-01-01", archive_path="/tmp/empty.jsonl")


# --- key rotation --------------------------------------------------------------------------------


def test_one_verify_walks_a_chain_that_spans_a_rotation(
    ledger: tuple[SqlLedgerStore, str],
) -> None:
    store, db = ledger
    store.close()

    rotated = SqlLedgerStore(Session(create_ledger_engine(db)), NEW_KEY, previous_keys=[OLD_KEY])
    rotated.append(_entry(6, month=10))
    rotated.append(_entry(7, month=10))

    result = rotated.verify()
    assert result.ok is True, result.detail
    assert result.checked == 8

    written = {e.seq: e.key_id for e in rotated.entries_between()}
    assert written[1] == key_fingerprint(OLD_KEY)
    assert written[7] == key_fingerprint(NEW_KEY)


def test_discarding_a_retired_key_is_reported_as_exactly_that(
    ledger: tuple[SqlLedgerStore, str],
) -> None:
    """Not as tampering: the records are fine, the operator threw away what verifies them."""
    store, db = ledger
    store.close()

    without_the_old_key = SqlLedgerStore(Session(create_ledger_engine(db)), NEW_KEY)
    result = without_the_old_key.verify()

    assert result.ok is False
    assert "not configured" in result.detail
    assert "GATEKEEPER_HMAC_KEY_PREVIOUS" in result.detail


def test_records_written_before_rotation_existed_still_verify(tmp_path: Path) -> None:
    """An existing ledger, upgraded: its rows carry no key fingerprint at all."""
    db = str(tmp_path / "legacy.db")
    migrate(db)
    store = SqlLedgerStore(Session(create_ledger_engine(db)), OLD_KEY)
    store.append(_entry(0, month=1))
    store.close()

    connection = sqlite3.connect(db)  # simulate rows written before the column existed
    connection.execute("UPDATE ledger_entry SET key_id = ''")
    connection.commit()
    connection.close()

    reopened = SqlLedgerStore(Session(create_ledger_engine(db)), NEW_KEY, previous_keys=[OLD_KEY])
    assert reopened.verify().ok is True


def test_tampering_is_still_caught_after_a_rotation(ledger: tuple[SqlLedgerStore, str]) -> None:
    """The keyring must not become a way to launder an altered record."""
    store, db = ledger
    store.close()
    connection = sqlite3.connect(db)
    connection.execute("UPDATE ledger_entry SET reason = 'looks fine' WHERE seq = 2")
    connection.commit()
    connection.close()

    rotated = SqlLedgerStore(Session(create_ledger_engine(db)), NEW_KEY, previous_keys=[OLD_KEY])
    result = rotated.verify()
    assert result.ok is False
    assert result.broken_at == 2
