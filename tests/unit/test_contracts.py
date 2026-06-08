"""Contract tests: typed models validate, and boundary units/scales agree on both sides."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from gatekeeper.schemas.enums import ActionKind, Verdict
from gatekeeper.schemas.ledger import GENESIS_HASH, HASH_HEX_LEN, LedgerEntry
from gatekeeper.schemas.models import Decision, Principal, RiskAssessment, ToolCall


# --- typed models, not raw dicts -------------------------------------------
def test_principal_defaults_and_is_frozen():
    p = Principal(id="alice", role="operator")
    assert p.tenant == "default"  # isolation seam default
    with pytest.raises(ValidationError):
        p.id = "bob"  # frozen — identity can't be mutated after resolution


def test_toolcall_defaults():
    c = ToolCall(call_id="c1", upstream="demo-files", tool="read_file")
    assert c.action_kind is ActionKind.UNKNOWN
    assert c.arguments == {}


def test_enum_string_values():
    assert Verdict.DENY == "deny"
    assert ActionKind.WRITE == "write"


# --- units / scale pinned: risk is ALWAYS 0.0..1.0 -------------------------
@pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0])
def test_risk_must_be_within_0_1(bad: float):
    with pytest.raises(ValidationError):
        Decision(call_id="c1", verdict=Verdict.DENY, reason="x", risk=bad)
    with pytest.raises(ValidationError):
        RiskAssessment(risk=bad, is_write=True, reason="x")


def test_risk_scale_agrees_across_config_and_code_boundary():
    # The config threshold MUST be on the same 0..1 scale as Decision.risk / RiskAssessment.risk.
    product = yaml.safe_load(Path("config/product.yaml").read_text(encoding="utf-8"))
    threshold = product["risk"]["approve_threshold"]
    assert 0.0 <= threshold <= 1.0


# --- ledger contract -------------------------------------------------------
def test_genesis_hash_is_hash_width():
    assert len(GENESIS_HASH) == HASH_HEX_LEN == 64


def test_ledger_entry_minimal_construct():
    e = LedgerEntry(
        call_id="c1",
        ts="2026-06-07T17:00:00+00:00",
        principal="alice",
        role="operator",
        upstream="demo-files",
        tool="read_file",
        action_kind=ActionKind.READ,
        verdict=Verdict.ALLOW,
        reason="ok",
        payload_hash="a" * 64,
        prev_hash=GENESIS_HASH,
        entry_hash="b" * 64,
    )
    assert e.seq is None and e.tenant == "default" and e.schema_version == 1
