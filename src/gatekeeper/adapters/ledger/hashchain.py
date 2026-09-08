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
#:
#: ``key_id`` is excluded deliberately. It names WHICH key signed an entry, so a rotated key can
#: still verify what the old one wrote — and it must not change the payload, or every entry written
#: before rotation existed would stop verifying the day the column was added. Excluding it is safe:
#: the keys themselves come from the operator's environment, never from the ledger, so relabelling
#: an entry's ``key_id`` makes verification FAIL rather than pass under an attacker's key.
_EXCLUDED: set[str] = {"seq", "prev_hash", "entry_hash", "key_id"}


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


def key_fingerprint(key: str) -> str:
    """A short, public label for an HMAC key — safe to store next to the entries it signed.

    It is a hash of the key, not the key: it identifies which secret was used without being usable
    to forge anything. Rotation writes new entries under a new fingerprint while the old entries
    keep theirs, which is what lets one ``verify`` walk a chain that spans a rotation.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def compute_checkpoint_hash(key: str, checkpoint: Any) -> str:
    """Keyed HMAC over a retention checkpoint's claims (everything except its own id and hash).

    This is what makes a prune accountable: the statement "records 1..900 were archived and
    removed, and the chain stood at <hash>" is itself signed, so it cannot be added, edited or
    backdated by someone without the key.
    """
    claims = checkpoint.model_dump(mode="json", exclude={"id", "checkpoint_hash"})
    message = _canonical_json(claims).encode("utf-8")
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()
