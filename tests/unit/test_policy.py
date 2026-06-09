"""Unit tests for the CedarPolicyEngine — RBAC policy-as-code, in isolation (no ledger/upstream).

Pins the authorization contract + its fail-closed guarantees:
  * readonly may READ but not WRITE; operator/admin may write; an unknown role gets nothing,
  * the default decision is DENY (nothing a permit doesn't grant is allowed),
  * a missing / empty / unparseable policy refuses to LOAD (fail-loud at boot),
  * an odd tool name can't break or inject into the Cedar request (escaping),
  * the deny carries a human-readable reason for the audit record.
"""

from __future__ import annotations

import pytest

from gatekeeper.adapters.policy.cedar import CedarPolicyEngine
from gatekeeper.config.loader import ConfigError
from gatekeeper.schemas.enums import ActionKind, Verdict
from gatekeeper.schemas.models import Principal, ToolCall

# The real, version-controlled policy this product ships with.
POLICY_DIR = "policies"


def _engine() -> CedarPolicyEngine:
    return CedarPolicyEngine.from_config(POLICY_DIR)


def _call(tool: str, action: ActionKind, upstream: str = "demo") -> ToolCall:
    return ToolCall(call_id="c1", upstream=upstream, tool=tool, arguments={}, action_kind=action)


def _who(role: str, pid: str = "u") -> Principal:
    return Principal(id=pid, role=role)


@pytest.mark.parametrize(
    ("role", "action", "expected"),
    [
        ("readonly", ActionKind.READ, Verdict.ALLOW),
        ("readonly", ActionKind.WRITE, Verdict.DENY),  # the headline RBAC case
        ("operator", ActionKind.READ, Verdict.ALLOW),
        ("operator", ActionKind.WRITE, Verdict.ALLOW),
        ("admin", ActionKind.READ, Verdict.ALLOW),
        ("admin", ActionKind.WRITE, Verdict.ALLOW),
    ],
)
def test_rbac_matrix(role: str, action: ActionKind, expected: Verdict) -> None:
    decision = _engine().evaluate(_who(role), _call("write_file", action))
    assert decision.verdict is expected
    assert decision.call_id == "c1"
    assert decision.reason  # always carries a why for the audit record


def test_unknown_role_is_denied_fail_closed() -> None:
    # A principal whose role matches no permit gets nothing (default-deny), not an error.
    decision = _engine().evaluate(_who("intern"), _call("read_file", ActionKind.READ))
    assert decision.verdict is Verdict.DENY


def test_unknown_action_kind_denied_for_readonly() -> None:
    # readonly only permits action == read; an UNKNOWN action is not read -> deny (fail-closed).
    decision = _engine().evaluate(_who("readonly"), _call("mystery", ActionKind.UNKNOWN))
    assert decision.verdict is Verdict.DENY


def test_deny_reason_names_role_action_resource() -> None:
    decision = _engine().evaluate(_who("readonly"), _call("delete_file", ActionKind.WRITE, "fs"))
    assert decision.verdict is Verdict.DENY
    assert "readonly" in decision.reason
    assert "write" in decision.reason
    assert "fs::delete_file" in decision.reason


def test_odd_tool_name_does_not_break_evaluation() -> None:
    # A tool id containing a quote/backslash must be escaped, not injected into Cedar syntax.
    engine = _engine()
    allow = engine.evaluate(_who("admin"), _call('weird"\\name', ActionKind.WRITE))
    assert allow.verdict is Verdict.ALLOW
    deny = engine.evaluate(_who("readonly"), _call('weird"\\name', ActionKind.WRITE))
    assert deny.verdict is Verdict.DENY


def test_missing_policy_dir_fails_loud(tmp_path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        CedarPolicyEngine.from_config(tmp_path / "nope")


def test_empty_policy_dir_fails_loud(tmp_path) -> None:
    with pytest.raises(ConfigError, match="No .cedar"):
        CedarPolicyEngine.from_config(tmp_path)


def test_unparseable_policy_fails_loud(tmp_path) -> None:
    (tmp_path / "broken.cedar").write_text("permit (principal is not-cedar", encoding="utf-8")
    with pytest.raises(ConfigError, match="Could not parse"):
        CedarPolicyEngine.from_config(tmp_path)


def test_comments_only_policy_fails_loud(tmp_path) -> None:
    # Syntactically valid but defines no permit/forbid -> would silently deny every call.
    # The load guard must refuse this (fail-loud), not boot into an accidental deny-all.
    (tmp_path / "empty.cedar").write_text("// a policy with no rules\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="no permit/forbid"):
        CedarPolicyEngine.from_config(tmp_path)


def test_evaluation_error_is_fail_closed_deny() -> None:
    # If the underlying policy text is garbage at eval time, evaluate must DENY, never raise/allow.
    engine = CedarPolicyEngine(policy_text="this is not valid cedar")
    decision = engine.evaluate(_who("admin"), _call("read_file", ActionKind.READ))
    assert decision.verdict is Verdict.DENY
    assert "denied" in decision.reason.lower() or "error" in decision.reason.lower()
