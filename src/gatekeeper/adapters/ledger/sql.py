"""SQL ``LedgerStore`` — append-only, keyed-HMAC hash-chained audit trail.

Implements ``ports.ledger.LedgerStore`` over either engine the gateway supports: the local SQLite
file or a hosted Postgres database (``gatekeeper.db.base`` decides which from config). ``append``
is the ONLY write path (no update/delete), so the log is append-only by construction. ``verify``
walks the chain and pinpoints the first break.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from gatekeeper.adapters.ledger.hashchain import (
    compute_checkpoint_hash,
    compute_entry_hash,
    key_fingerprint,
)
from gatekeeper.db.base import lock_chain
from gatekeeper.db.models import LedgerCheckpointRow, LedgerEntryRow
from gatekeeper.schemas.ledger import GENESIS_HASH, Checkpoint, LedgerEntry, VerifyResult


class SqlLedgerStore:
    """Append + verify a tamper-evident ledger. ``key`` is the HMAC key (from .env, fail-closed).

    ``previous_keys`` are retired chain keys. New entries are always signed with ``key``; entries
    written before a rotation are verified with the key that signed them, looked up by the
    fingerprint stored on the row. Without this, rotating the chain key would silently turn every
    existing record into an unverifiable one — which in practice means nobody ever rotates it.
    """

    def __init__(self, session: Session, key: str, previous_keys: Sequence[str] = ()) -> None:
        self._session = session
        self._key = key
        self._key_id = key_fingerprint(key)
        #: fingerprint -> key, for verification only.
        self._keyring = {key_fingerprint(k): k for k in (key, *previous_keys)}

    @property
    def engine(self) -> Any:
        """The engine this store's session is bound to (for sibling sessions on the same file)."""
        return self._session.get_bind()

    # --- helpers -----------------------------------------------------------
    @staticmethod
    def _to_entry(row: LedgerEntryRow) -> LedgerEntry:
        return LedgerEntry.model_validate(row, from_attributes=True)

    def _last_hash(self) -> str:
        last = self._session.execute(
            select(LedgerEntryRow.entry_hash).order_by(LedgerEntryRow.seq.desc()).limit(1)
        ).scalar_one_or_none()
        return last if last is not None else GENESIS_HASH

    # --- LedgerStore port --------------------------------------------------
    def append(self, entry: LedgerEntry) -> LedgerEntry:
        """Chain + persist one entry. Raises on failure (so callers can fail-closed).

        The read of the chain head and the insert happen in ONE write transaction that holds the
        chain lock throughout (``BEGIN IMMEDIATE`` on SQLite, a transaction-scoped advisory lock on
        Postgres), so no other writer — in this process, another process, or another replica — can
        slip in between and fork the chain. A failed commit is rolled back before re-raising: the
        session stays usable, so one full disk or lock timeout denies *that* call, not every call
        until restart. The returned entry is built before the commit, so no follow-up read (which
        would take the lock again and hold it) is ever needed.
        """
        try:
            lock_chain(self._session)
            prev_hash = self._last_hash()
            entry_hash = compute_entry_hash(self._key, prev_hash, entry)
            # Derive columns from the model (mode="json" -> enums as values) so adding a field
            # never silently drops it here. The chain fields are set by the store, not the caller.
            row = LedgerEntryRow(
                **entry.model_dump(
                    mode="json", exclude={"seq", "prev_hash", "entry_hash", "key_id"}
                ),
                prev_hash=prev_hash,
                entry_hash=entry_hash,
                key_id=self._key_id,
            )
            self._session.add(row)
            self._session.flush()  # assigns seq
            stored = self._to_entry(row)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return stored

    def read(self, *, limit: int = 100, principal: str | None = None) -> Sequence[LedgerEntry]:
        stmt = select(LedgerEntryRow).order_by(LedgerEntryRow.seq.desc()).limit(limit)
        if principal is not None:  # tenant/owner isolation on reads
            stmt = stmt.where(LedgerEntryRow.principal == principal)
        try:
            rows = self._session.execute(stmt).scalars().all()
            return [self._to_entry(r) for r in rows]
        finally:
            self._session.rollback()  # a read must not keep the write lock (see engine setup)

    def get(self, call_id: str) -> LedgerEntry | None:
        try:
            row = self._session.execute(
                select(LedgerEntryRow)
                .where(LedgerEntryRow.call_id == call_id)
                .order_by(LedgerEntryRow.seq)
                .limit(1)
            ).scalar_one_or_none()
            return self._to_entry(row) if row is not None else None
        finally:
            self._session.rollback()

    def lifecycle(self, call_id_prefix: str) -> tuple[list[LedgerEntry], int]:
        """Every entry of the ONE call whose id starts with ``call_id_prefix``, oldest first, plus
        how many distinct call ids matched (0 = none, 1 = found, >1 = ambiguous: entries empty)."""
        try:
            rows = (
                self._session.execute(
                    select(LedgerEntryRow)
                    .where(LedgerEntryRow.call_id.like(f"{call_id_prefix}%"))
                    .order_by(LedgerEntryRow.seq)
                )
                .scalars()
                .all()
            )
            matches = sorted({r.call_id for r in rows})
            if len(matches) != 1:
                return [], len(matches)
            return [self._to_entry(r) for r in rows], 1
        finally:
            self._session.rollback()

    def head(self) -> str:
        """The newest entry's hash (or the genesis hash for an empty ledger)."""
        try:
            return self._last_hash()
        finally:
            self._session.rollback()

    def verify(self, *, expected_head: str | None = None) -> VerifyResult:
        """Walk the chain oldest→newest; recompute each hash + check linkage.

        Detects any altered, inserted, reordered, or removed record — except records removed from
        the *end* of the chain, which leave a shorter but valid chain behind. Pass the head hash
        you pinned earlier (``gatekeeper verify`` prints it) as ``expected_head`` to close that
        gap: a chain whose head differs from the pinned one is reported as truncated.

        Two things make this work on a ledger that has been operated rather than merely kept:

        * **A rotated key.** Each entry names the key that signed it, so the walk uses that key.
          A chain spanning a rotation verifies in one pass; an entry signed by a key nobody
          configured is reported as exactly that, instead of as tampering.
        * **A retention cut.** If records were archived and removed, the walk resumes from the
          signed checkpoint rather than from the genesis hash — after checking the checkpoint's own
          signature, so a prune can be accounted for but not invented.
        """
        checkpoint = self.latest_checkpoint()
        if checkpoint is not None:
            problem = self._checkpoint_problem(checkpoint)
            if problem:
                return VerifyResult(
                    ok=False,
                    checked=0,
                    broken_at=checkpoint.through_seq,
                    head=None,
                    detail=problem,
                    checkpoint=checkpoint,
                )
        try:
            rows = (
                self._session.execute(select(LedgerEntryRow).order_by(LedgerEntryRow.seq.asc()))
                .scalars()
                .all()
            )
            entries = [self._to_entry(r) for r in rows]
        finally:
            self._session.rollback()
        expected_prev = checkpoint.through_hash if checkpoint else GENESIS_HASH
        checked = 0
        for row in entries:
            if row.prev_hash != expected_prev:
                return VerifyResult(
                    ok=False,
                    checked=checked,
                    broken_at=row.seq,
                    head=expected_prev,
                    detail="prev_hash linkage broken (entry removed, reordered, or inserted)",
                    checkpoint=checkpoint,
                )
            candidates = self._keys_for(row.key_id)
            if not candidates:
                return VerifyResult(
                    ok=False,
                    checked=checked,
                    broken_at=row.seq,
                    head=expected_prev,
                    detail=(
                        f"entry was signed with key {row.key_id!r}, which is not configured. "
                        "Add it to GATEKEEPER_HMAC_KEY_PREVIOUS to verify records written before "
                        "the last rotation"
                    ),
                    checkpoint=checkpoint,
                )
            recomputed = next(
                (
                    candidate
                    for candidate in (compute_entry_hash(k, row.prev_hash, row) for k in candidates)
                    if candidate == row.entry_hash
                ),
                compute_entry_hash(candidates[0], row.prev_hash, row),
            )
            if recomputed != row.entry_hash:
                return VerifyResult(
                    ok=False,
                    checked=checked,
                    broken_at=row.seq,
                    head=expected_prev,
                    detail="entry_hash mismatch (record altered or wrong key)",
                    checkpoint=checkpoint,
                )
            checked += 1
            expected_prev = row.entry_hash
        if expected_head is not None and expected_head != expected_prev:
            return VerifyResult(
                ok=False,
                checked=checked,
                broken_at=None,
                head=expected_prev,
                detail="head does not match the pinned head (entries removed from the end, or "
                "the pin is stale)",
                checkpoint=checkpoint,
            )
        detail = "chain intact"
        if checkpoint is not None:
            detail += (
                f" (resumed from a signed retention checkpoint: {checkpoint.pruned_count} "
                f"records through seq {checkpoint.through_seq} were archived on "
                f"{checkpoint.created_at[:10]})"
            )
        return VerifyResult(
            ok=True, checked=checked, head=expected_prev, detail=detail, checkpoint=checkpoint
        )

    # --- keys, checkpoints, retention --------------------------------------
    def _keys_for(self, key_id: str) -> list[str]:
        """The key(s) that could have signed an entry, best candidate first.

        A named fingerprint identifies exactly one key. An EMPTY fingerprint means the entry was
        written before the ledger recorded which key it used, so every configured key is a
        candidate — that is what lets an existing ledger keep verifying after an upgrade, and
        after a rotation, without rewriting a single stored record.
        """
        if key_id:
            key = self._keyring.get(key_id)
            return [key] if key is not None else []
        return list(self._keyring.values())

    def latest_checkpoint(self) -> Checkpoint | None:
        """The most recent signed retention cut, if this ledger has been pruned."""
        try:
            row = self._session.execute(
                select(LedgerCheckpointRow).order_by(LedgerCheckpointRow.id.desc()).limit(1)
            ).scalar_one_or_none()
            return Checkpoint.model_validate(row, from_attributes=True) if row else None
        finally:
            self._session.rollback()

    def _checkpoint_problem(self, checkpoint: Checkpoint) -> str:
        """Empty if the checkpoint is genuine; otherwise why it cannot be trusted."""
        candidates = self._keys_for(checkpoint.key_id)
        if not candidates:
            return (
                f"the retention checkpoint was signed with key {checkpoint.key_id!r}, which is "
                "not configured"
            )
        if any(
            compute_checkpoint_hash(k, checkpoint) == checkpoint.checkpoint_hash for k in candidates
        ):
            return ""
        return (
            "the retention checkpoint's signature does not match: records were removed and the "
            "account of their removal was altered or forged"
        )

    def entries_before(self, cutoff_ts: str, *, batch: int = 500) -> Iterator[LedgerEntry]:
        """Stream every entry older than ``cutoff_ts`` (UTC ISO-8601), oldest first.

        Streamed in batches so exporting a year of records costs bounded memory, and so a long
        export never holds a transaction open across the whole read.
        """
        yield from self._stream(cutoff_ts=cutoff_ts, since_ts=None, batch=batch)

    def entries_between(
        self, *, since_ts: str | None = None, until_ts: str | None = None, batch: int = 500
    ) -> Iterator[LedgerEntry]:
        """Stream entries in a time window, oldest first — the export path."""
        yield from self._stream(cutoff_ts=until_ts, since_ts=since_ts, batch=batch)

    def _stream(
        self, *, cutoff_ts: str | None, since_ts: str | None, batch: int
    ) -> Iterator[LedgerEntry]:
        after_seq = 0
        while True:
            stmt = select(LedgerEntryRow).where(LedgerEntryRow.seq > after_seq)
            if cutoff_ts is not None:
                stmt = stmt.where(LedgerEntryRow.ts < cutoff_ts)
            if since_ts is not None:
                stmt = stmt.where(LedgerEntryRow.ts >= since_ts)
            stmt = stmt.order_by(LedgerEntryRow.seq.asc()).limit(batch)
            try:
                rows = self._session.execute(stmt).scalars().all()
            finally:
                self._session.rollback()
            if not rows:
                return
            for row in rows:
                yield self._to_entry(row)
            after_seq = rows[-1].seq

    def prune_before(self, cutoff_ts: str, *, archive_path: str, note: str = "") -> Checkpoint:
        """Remove every entry older than ``cutoff_ts`` and leave a signed account of the removal.

        The caller MUST have written the archive first and passed its path: this method is the
        deletion half of a retention run, and a deletion with nowhere to read the records back
        from is not retention, it is loss.

        Everything happens in one locked transaction — the same lock ``append`` takes — so a call
        being audited concurrently cannot land between the cut and the checkpoint.
        """
        try:
            lock_chain(self._session)
            last = self._session.execute(
                select(LedgerEntryRow)
                .where(LedgerEntryRow.ts < cutoff_ts)
                .order_by(LedgerEntryRow.seq.desc())
                .limit(1)
            ).scalar_one_or_none()
            if last is None:
                raise ValueError(f"nothing in the ledger is older than {cutoff_ts}")
            pruned = (
                self._session.execute(
                    select(LedgerEntryRow.seq).where(LedgerEntryRow.seq <= last.seq)
                )
                .scalars()
                .all()
            )
            checkpoint = Checkpoint(
                created_at=datetime.now(UTC).isoformat(),
                through_seq=last.seq,
                through_hash=last.entry_hash,
                pruned_count=len(pruned),
                archive_path=archive_path,
                note=note,
                key_id=self._key_id,
            )
            signed = checkpoint.model_copy(
                update={"checkpoint_hash": compute_checkpoint_hash(self._key, checkpoint)}
            )
            self._session.add(LedgerCheckpointRow(**signed.model_dump(mode="json", exclude={"id"})))
            self._session.execute(delete(LedgerEntryRow).where(LedgerEntryRow.seq <= last.seq))
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return signed

    def close(self) -> None:
        self._session.close()
