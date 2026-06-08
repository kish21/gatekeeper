"""Ledger port: append-only, tamper-evident audit store. Implemented by adapters.ledger.sqlite."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from gatekeeper.schemas.ledger import LedgerEntry, VerifyResult


class LedgerStore(Protocol):
    """Persist and verify the hash-chained audit trail.

    Contract: ``append`` is the ONLY write path and is append-only (no update/delete). It sets
    ``seq``/``prev_hash``/``entry_hash`` and returns the stored entry. A failed append MUST raise so
    the caller can fail-closed (no un-audited calls).
    """

    def append(self, entry: LedgerEntry) -> LedgerEntry: ...

    def read(self, *, limit: int = 100, principal: str | None = None) -> Sequence[LedgerEntry]: ...

    def get(self, call_id: str) -> LedgerEntry | None: ...

    def verify(self) -> VerifyResult: ...
