"""Keyed-HMAC hash-chain math for the tamper-evident ledger. Pure functions, no I/O.

    entry_hash = HMAC-SHA256(key, prev_hash + canonical_payload(entry))

``canonical_payload`` excludes the store-computed fields (``seq``/``prev_hash``/``entry_hash``) and
serializes deterministically (sorted keys, no whitespace) so an entry always hashes the same way.
The key comes from ``.env`` (GATEKEEPER_HMAC_KEY) — an attacker who edits a row but lacks the key
cannot recompute a valid chain, which is what makes the log tamper-EVIDENT.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from typing import Any

from gatekeeper.schemas.ledger import LedgerEntry

#: Fields NOT part of the hashed payload (store-computed / chain linkage).
_EXCLUDED: set[str] = {"seq", "prev_hash", "entry_hash"}


def _canonical_json(data: Any, *, default: Callable[[Any], Any] | None = None) -> str:
    """The ONE canonicalization: sorted keys, no whitespace. Both hashes below share it."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=default)


def canonical_payload(entry: LedgerEntry) -> str:
    """Deterministic JSON of an entry's business fields (sorted keys, compact, enums as values)."""
    return _canonical_json(entry.model_dump(mode="json", exclude=_EXCLUDED))


def compute_payload_hash(key: str, arguments: dict[str, Any]) -> str:
    """Keyed HMAC-SHA256 of a tool call's arguments (PII-safe fingerprint for the ledger).

    Raw arguments are NEVER persisted (they may carry secrets/PII); only this keyed digest is
    stored, so an auditor can still prove "the same arguments were called twice" without the gateway
    keeping the plaintext. Canonicalized (sorted keys, compact) so identical args hash identically.
    """
    canonical = _canonical_json(arguments, default=str)
    return hmac.new(key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def compute_entry_hash(key: str, prev_hash: str, entry: LedgerEntry) -> str:
    """Return the keyed HMAC-SHA256 hex digest linking ``entry`` to ``prev_hash``."""
    message = (prev_hash + canonical_payload(entry)).encode("utf-8")
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()
