"""The audit-ledger contracts — the wedge.

``LedgerEntry`` is the typed DTO mirrored 1:1 by ``db.models.LedgerEntryRow``.
Integrity model (implemented by the ledger adapter in /build):
    entry_hash = HMAC-SHA256(key, prev_hash + canonical_json(entry-without-hashes))
so each record is cryptographically chained to the one before it.

PII stance: raw arguments and raw upstream output are NEVER stored — only ``payload_hash`` (an HMAC
of the canonical arguments) and a redacted ``result_summary``. Full-capture is a deferred,
config-gated option for non-sensitive upstreams only.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from gatekeeper.schemas.enums import ActionKind, Verdict

#: prev_hash of the very first entry (no predecessor). 64 hex chars to match HMAC-SHA256 width.
GENESIS_HASH = "0" * 64
#: Bump when the ledger field set changes; persisted on every row for forward/back-compat.
LEDGER_SCHEMA_VERSION = 1
#: Width of a hex SHA-256 / HMAC-SHA256 digest.
HASH_HEX_LEN = 64


class LedgerEntry(BaseModel):
    """One tamper-evident audit record. ``seq``/hashes are set by the store on append."""

    seq: int | None = Field(default=None, description="Monotonic chain order (DB autoincrement).")
    call_id: str
    ts: str = Field(description="UTC ISO-8601, e.g. '2026-06-07T17:00:00+00:00'. Always UTC.")
    tenant: str = "default"
    principal: str
    role: str
    upstream: str
    tool: str
    action_kind: ActionKind
    verdict: Verdict
    reason: str
    payload_hash: str = Field(description="HMAC-SHA256 hex of canonical arguments (PII-safe).")
    result_summary: str = Field(default="", description="Redacted/truncated; never raw output.")
    risk: float | None = Field(default=None, ge=0.0, le=1.0, description="0.0..1.0 (M2).")
    key_id: str = Field(
        default="",
        description="Fingerprint of the HMAC key that signed this entry, so a rotated key can "
        "still verify what the old one wrote. Set by the store; not part of the hashed payload.",
    )
    prev_hash: str | None = Field(
        default=None, description="Predecessor's entry_hash; set by the store on append."
    )
    entry_hash: str | None = Field(
        default=None, description="Keyed HMAC of this entry; set by the store on append."
    )
    schema_version: int = LEDGER_SCHEMA_VERSION


class Checkpoint(BaseModel):
    """A signed statement that entries up to ``through_seq`` were archived and removed.

    Retention and a hash chain are in tension: a chain proves nothing was removed, and a retention
    policy exists to remove things. Deleting rows quietly would leave a shorter chain that still
    verifies against the genesis hash — exactly the "tail truncation" an auditor is entitled to
    detect. So a prune is not silent: it records where the cut was, what the chain's state was at
    that point, and how many records went, and it signs that statement with the ledger key.

    ``verify`` then resumes from ``through_hash`` instead of the genesis hash, and reports the
    checkpoint. A forged or edited checkpoint fails its own HMAC, so removing records without
    leaving a valid, signed account of the removal remains impossible.
    """

    id: int | None = Field(default=None, description="Autoincrement; checkpoints are ordered.")
    created_at: str = Field(description="UTC ISO-8601 when the prune ran.")
    through_seq: int = Field(description="The last seq that was archived and removed.")
    through_hash: str = Field(description="entry_hash of that record: where the chain resumes.")
    pruned_count: int = Field(description="How many records were removed.")
    archive_path: str = Field(default="", description="Where they were written before removal.")
    note: str = Field(default="", description="Why, e.g. 'retention: 400 days'.")
    key_id: str = Field(default="", description="Fingerprint of the key that signed this.")
    checkpoint_hash: str | None = Field(
        default=None, description="Keyed HMAC of the statement above; set on write."
    )


class VerifyResult(BaseModel):
    """Output of ``gatekeeper verify`` — proof the chain is intact (or where it broke)."""

    ok: bool
    checked: int = Field(description="Number of entries walked.")
    broken_at: int | None = Field(
        default=None, description="seq of the first broken entry, if any."
    )
    head: str | None = Field(
        default=None,
        description="Hash of the last verified entry (pin it; pass it back as expected_head).",
    )
    detail: str = ""
    checkpoint: Checkpoint | None = Field(
        default=None,
        description="The signed retention cut this verification resumed from, if there was one.",
    )
