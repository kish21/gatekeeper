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
    prev_hash: str | None = Field(
        default=None, description="Predecessor's entry_hash; set by the store on append."
    )
    entry_hash: str | None = Field(
        default=None, description="Keyed HMAC of this entry; set by the store on append."
    )
    schema_version: int = LEDGER_SCHEMA_VERSION


class VerifyResult(BaseModel):
    """Output of ``gatekeeper verify`` — proof the chain is intact (or where it broke)."""

    ok: bool
    checked: int = Field(description="Number of entries walked.")
    broken_at: int | None = Field(
        default=None, description="seq of the first broken entry, if any."
    )
    detail: str = ""
