"""Typed domain DTOs that cross the gateway's internal boundaries.

These are the contracts between transport, gateway, and the adapter ports — no raw dicts cross a
boundary. Units/scale are pinned here (see the boundary table in PRODUCT.md#Contracts):
  * ``risk`` is a float in [0.0, 1.0]  (0.0 = safe, 1.0 = dangerous) — the SAME scale everywhere.
  * ``call_id`` is a UUID4 string minted once at ingress (the idempotency / natural key).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from gatekeeper.schemas.enums import ActionKind, Verdict


class Principal(BaseModel):
    """Resolved caller identity — the output of an ``IdentityResolver`` (auth boundary)."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(description="Stable principal id, e.g. 'alice'.")
    role: str = Field(description="Role name the policy engine uses, e.g. 'operator'.")
    tenant: str = Field(default="default", description="Isolation seam (multi-tenant deferred).")


class ToolCall(BaseModel):
    """A single intercepted MCP tool call (transport -> gateway)."""

    call_id: str = Field(description="UUID4 minted at ingress; idempotency / natural key.")
    upstream: str = Field(description="Registered upstream name (config/upstreams.yaml).")
    tool: str = Field(description="Tool name on that upstream.")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw args. NEVER persisted raw (PII) — hashed into the ledger's payload_hash.",
    )
    action_kind: ActionKind = ActionKind.UNKNOWN


class ToolResult(BaseModel):
    """Result of forwarding a call to an upstream (upstream -> gateway)."""

    call_id: str
    ok: bool
    summary: str = Field(
        default="", description="Short, redacted/truncated status — NOT raw output."
    )


class Decision(BaseModel):
    """Governance decision for a call (policy / gateway output)."""

    call_id: str
    verdict: Verdict
    reason: str = Field(description="Human-readable why, recorded in the ledger.")
    risk: float | None = Field(
        default=None, ge=0.0, le=1.0, description="0.0..1.0 risk (M2). None until scored."
    )


class RiskAssessment(BaseModel):
    """M2: LLM risk classification — output of the RiskClassifier via an ``LLMProvider``."""

    risk: float = Field(
        ge=0.0, le=1.0, description="0.0 (safe) .. 1.0 (dangerous). Same scale as Decision.risk."
    )
    is_write: bool
    reason: str
