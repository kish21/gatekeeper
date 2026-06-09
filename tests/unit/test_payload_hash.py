"""Unit tests for the keyed payload-hash helper (PII-safe argument fingerprint)."""

from __future__ import annotations

from gatekeeper.adapters.ledger.hashchain import compute_payload_hash
from gatekeeper.schemas.ledger import HASH_HEX_LEN

KEY = "k" * 64


def test_deterministic_and_key_order_insensitive() -> None:
    a = compute_payload_hash(KEY, {"b": 2, "a": 1})
    b = compute_payload_hash(KEY, {"a": 1, "b": 2})  # same content, different insertion order
    assert a == b
    assert len(a) == HASH_HEX_LEN


def test_content_change_changes_hash() -> None:
    assert compute_payload_hash(KEY, {"a": 1}) != compute_payload_hash(KEY, {"a": 2})


def test_key_change_changes_hash() -> None:
    args = {"path": "secret.txt"}
    assert compute_payload_hash(KEY, args) != compute_payload_hash("z" * 64, args)


def test_empty_arguments_hashes_stably() -> None:
    assert compute_payload_hash(KEY, {}) == compute_payload_hash(KEY, {})
