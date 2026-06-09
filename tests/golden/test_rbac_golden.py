"""Golden / eval suite for RBAC policy-as-code.

The authorization decision is M1's quality-critical, regression-prone surface: the contract lives in
a hand-editable ``policies/gatekeeper.cedar`` file, so a well-meaning edit can silently widen or
narrow access. This eval pins the contract as a labeled dataset (``rbac_golden.yaml``: known
``(role, action, upstream, tool) -> expected verdict``) and runs every case through the REAL shipped
Cedar engine. A drift in the policy fails here, naming the offending case — the same shape the M2
risk-classifier eval will take (labeled inputs -> expected output), so quality is measured.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from gatekeeper.adapters.policy.cedar import CedarPolicyEngine
from gatekeeper.schemas.enums import ActionKind, Verdict
from gatekeeper.schemas.models import Principal, ToolCall

# The REAL, version-controlled policy this product ships with (not a test fixture).
POLICY_DIR = "policies"
GOLDEN = Path(__file__).parent / "rbac_golden.yaml"


def _load_cases() -> list[dict[str, Any]]:
    data = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    cases = data["cases"]
    assert cases, "golden dataset must not be empty"
    return cases


def _case_id(case: dict[str, Any]) -> str:
    return f"{case['role']}-{case['action']}-{case['upstream']}::{case['tool']}->{case['expect']}"


CASES = _load_cases()


@pytest.fixture(scope="module")
def engine() -> CedarPolicyEngine:
    # Load the shipped policy ONCE; every golden case is evaluated against it.
    return CedarPolicyEngine.from_config(POLICY_DIR)


@pytest.mark.parametrize("case", CASES, ids=[_case_id(c) for c in CASES])
def test_rbac_golden(engine: CedarPolicyEngine, case: dict[str, Any]) -> None:
    expected = Verdict.ALLOW if case["expect"] == "allow" else Verdict.DENY
    call = ToolCall(
        call_id="golden",
        upstream=case["upstream"],
        tool=case["tool"],
        arguments={},
        action_kind=ActionKind(case["action"]),
    )
    decision = engine.evaluate(Principal(id="who", role=case["role"]), call)
    assert decision.verdict is expected, (
        f"policy drift on {_case_id(case)}: got {decision.verdict.value} "
        f"(reason: {decision.reason})"
    )


def test_golden_covers_every_role_and_both_verdicts() -> None:
    # Guard the dataset itself: it must exercise all three roles and BOTH outcomes, so the eval
    # can't silently degrade into an all-allow or all-deny set that proves nothing.
    roles = {c["role"] for c in CASES}
    verdicts = {c["expect"] for c in CASES}
    assert {"readonly", "operator", "admin"} <= roles
    assert verdicts == {"allow", "deny"}
