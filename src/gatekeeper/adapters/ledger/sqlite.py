"""SQLite ``LedgerStore`` — append-only, keyed-HMAC hash-chained audit trail.

Implements ``ports.ledger.LedgerStore``. ``append`` is the ONLY write path (no update/delete), so
the log is append-only by construction. ``verify`` walks the chain and pinpoints the first break.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from gatekeeper.adapters.ledger.hashchain import compute_entry_hash
from gatekeeper.db.models import LedgerEntryRow
from gatekeeper.schemas.ledger import GENESIS_HASH, LedgerEntry, VerifyResult


class SqliteLedgerStore:
    """Append + verify a tamper-evident ledger. ``key`` is the HMAC key (from .env, fail-closed)."""

    def __init__(self, session: Session, key: str) -> None:
        self._session = session
        self._key = key

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

        The read of the chain head and the insert happen in ONE write transaction (the engine
        opens it with ``BEGIN IMMEDIATE``), so no other writer can slip in between. A failed
        commit is rolled back before re-raising: the session stays usable, so one full disk or
        lock timeout denies *that* call, not every call until restart.
        """
        try:
            prev_hash = self._last_hash()
            entry_hash = compute_entry_hash(self._key, prev_hash, entry)
            # Derive columns from the model (mode="json" -> enums as values) so adding a field
            # never silently drops it here. The chain fields are set by the store, not the caller.
            row = LedgerEntryRow(
                **entry.model_dump(mode="json", exclude={"seq", "prev_hash", "entry_hash"}),
                prev_hash=prev_hash,
                entry_hash=entry_hash,
            )
            self._session.add(row)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(row)
        return self._to_entry(row)

    def read(self, *, limit: int = 100, principal: str | None = None) -> Sequence[LedgerEntry]:
        stmt = select(LedgerEntryRow).order_by(LedgerEntryRow.seq.desc()).limit(limit)
        if principal is not None:  # tenant/owner isolation on reads
            stmt = stmt.where(LedgerEntryRow.principal == principal)
        rows = self._session.execute(stmt).scalars().all()
        return [self._to_entry(r) for r in rows]

    def get(self, call_id: str) -> LedgerEntry | None:
        row = self._session.execute(
            select(LedgerEntryRow)
            .where(LedgerEntryRow.call_id == call_id)
            .order_by(LedgerEntryRow.seq)
            .limit(1)
        ).scalar_one_or_none()
        return self._to_entry(row) if row is not None else None

    def head(self) -> str:
        """The newest entry's hash (or the genesis hash for an empty ledger)."""
        return self._last_hash()

    def verify(self, *, expected_head: str | None = None) -> VerifyResult:
        """Walk the chain oldest→newest; recompute each hash + check linkage.

        Detects any altered, inserted, reordered, or removed record — except records removed from
        the *end* of the chain, which leave a shorter but valid chain behind. Pass the head hash
        you pinned earlier (``gatekeeper verify`` prints it) as ``expected_head`` to close that
        gap: a chain whose head differs from the pinned one is reported as truncated.
        """
        rows = (
            self._session.execute(select(LedgerEntryRow).order_by(LedgerEntryRow.seq.asc()))
            .scalars()
            .all()
        )
        expected_prev = GENESIS_HASH
        checked = 0
        for row in rows:
            if row.prev_hash != expected_prev:
                return VerifyResult(
                    ok=False,
                    checked=checked,
                    broken_at=row.seq,
                    head=expected_prev,
                    detail="prev_hash linkage broken (entry removed, reordered, or inserted)",
                )
            recomputed = compute_entry_hash(self._key, row.prev_hash, self._to_entry(row))
            if recomputed != row.entry_hash:
                return VerifyResult(
                    ok=False,
                    checked=checked,
                    broken_at=row.seq,
                    head=expected_prev,
                    detail="entry_hash mismatch (record altered or wrong key)",
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
            )
        return VerifyResult(ok=True, checked=checked, head=expected_prev, detail="chain intact")

    def close(self) -> None:
        self._session.close()
