"""Unit tests for the pure hash-chain math."""

from __future__ import annotations

from typing import Any

from gatekeeper.adapters.ledger.hashchain import canonical_payload, compute_entry_hash
from gatekeeper.schemas.enums import ActionKind, Verdict
from gatekeeper.schemas.ledger import GENESIS_HASH, LedgerEntry

KEY = "k" * 64


def _entry(**over: Any) -> LedgerEntry:
    base: dict[str, Any] = dict(
        call_id="c1",
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


def test_canonical_excludes_store_computed_fields():
    cp = canonical_payload(_entry(seq=5, prev_hash="x" * 64, entry_hash="y" * 64))
    assert "prev_hash" not in cp and "entry_hash" not in cp and '"seq"' not in cp


def test_hash_is_deterministic():
    e = _entry()
    assert compute_entry_hash(KEY, GENESIS_HASH, e) == compute_entry_hash(KEY, GENESIS_HASH, e)
    assert len(compute_entry_hash(KEY, GENESIS_HASH, e)) == 64  # hex sha256 width


def test_hash_changes_with_key_prev_and_content():
    e = _entry()
    h = compute_entry_hash(KEY, GENESIS_HASH, e)
    assert compute_entry_hash("z" * 64, GENESIS_HASH, e) != h  # different key
    assert compute_entry_hash(KEY, "f" * 64, e) != h  # different prev_hash
    assert compute_entry_hash(KEY, GENESIS_HASH, _entry(reason="changed")) != h  # different content
