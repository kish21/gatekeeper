"""Unit — who may release a held write, and what the ledger is allowed to claim about them.

The product's whole pitch is that an approval names a person. These tests hold that claim to
account: a name that was not proven must not pass on a network-facing desk, an approver must hold
an approver role, nobody approves their own call, and whatever happens the RECORD says which of
those it was.
"""

from __future__ import annotations

import pytest

from gatekeeper.domain.approval_rules import ApproverRules, approver_rules_from_config
from gatekeeper.domain.errors import ApprovalRefused
from gatekeeper.schemas.approval import ApprovalRequest, Approver
from gatekeeper.schemas.enums import ApproverMethod


def _held(principal: str = "alice") -> ApprovalRequest:
    return ApprovalRequest(
        id="ab12cd34",
        call_id="call-1",
        ts="2026-09-08T10:00:00+00:00",
        principal=principal,
        role="operator",
        upstream="github",
        tool="merge_pull_request",
        arguments_preview='{"pull_number": 7}',
    )


def _approver(id: str, role: str, method: ApproverMethod) -> Approver:
    return Approver(id=id, role=role, method=method)


NETWORK = ApproverRules(
    approver_roles=frozenset({"approver", "admin"}), four_eyes=True, require_verified=True
)
LAPTOP = ApproverRules(approver_roles=frozenset(), four_eyes=True, require_verified=False)


def test_a_typed_name_cannot_release_a_write_on_a_network_desk() -> None:
    """The blocker this feature exists for: 'approved by priya' must not be a self-assertion."""
    with pytest.raises(ApprovalRefused, match="a typed name proves nothing"):
        NETWORK.check(_held(), _approver("priya", "", ApproverMethod.LOCAL))


def test_a_signed_in_approver_may_release_a_write() -> None:
    NETWORK.check(_held(), _approver("priya", "approver", ApproverMethod.OIDC))


def test_a_personal_token_is_also_a_proven_identity() -> None:
    NETWORK.check(_held(), _approver("priya", "approver", ApproverMethod.TOKEN))


def test_being_able_to_reach_the_desk_is_not_being_an_approver() -> None:
    with pytest.raises(ApprovalRefused, match="may not decide held writes"):
        NETWORK.check(_held(), _approver("dave", "readonly", ApproverMethod.OIDC))


def test_nobody_approves_their_own_call() -> None:
    """Segregation of duties: without this the hold is a formality, not a gate."""
    with pytest.raises(ApprovalRefused, match="cannot also approve it"):
        NETWORK.check(_held(principal="priya"), _approver("priya", "approver", ApproverMethod.OIDC))


def test_four_eyes_can_be_turned_off_deliberately() -> None:
    rules = ApproverRules(approver_roles=frozenset({"admin"}), four_eyes=False)
    rules.check(_held(principal="root"), _approver("root", "admin", ApproverMethod.OIDC))


def test_a_typed_name_still_works_on_your_own_machine() -> None:
    """A single-person install must stay usable; the record marks the name as unproven."""
    LAPTOP.check(_held(), _approver("priya", "", ApproverMethod.LOCAL))


def test_console_approval_is_allowed_by_default_and_can_be_switched_off() -> None:
    console = _approver("ops-user", "", ApproverMethod.CONSOLE)
    NETWORK.check(_held(), console)  # a shell on the gateway host is a real, if weaker, identity

    hardened = ApproverRules(console_approvals=False, require_verified=True)
    with pytest.raises(ApprovalRefused, match="turned off here"):
        hardened.check(_held(), console)


def test_console_approval_still_obeys_four_eyes() -> None:
    ops = _approver("ops-user", "", ApproverMethod.CONSOLE)
    with pytest.raises(ApprovalRefused, match="cannot also approve it"):
        NETWORK.check(_held(principal="ops-user"), ops)


def test_rules_come_from_product_config() -> None:
    rules = approver_rules_from_config(
        {
            "approval": {
                "approver_roles": ["approver"],
                "four_eyes": False,
                "console_approvals": False,
            }
        },
        require_verified=True,
    )
    assert rules == ApproverRules(
        approver_roles=frozenset({"approver"}),
        four_eyes=False,
        console_approvals=False,
        require_verified=True,
    )


def test_defaults_are_the_safe_ones() -> None:
    """An operator who writes no approval block still gets four-eyes."""
    rules = approver_rules_from_config({}, require_verified=False)
    assert rules.four_eyes is True
    assert rules.approver_roles == frozenset()


@pytest.mark.parametrize(
    ("method", "verified"),
    [
        (ApproverMethod.OIDC, True),
        (ApproverMethod.TOKEN, True),
        (ApproverMethod.CONSOLE, False),
        (ApproverMethod.LOCAL, False),
    ],
)
def test_only_a_credential_counts_as_verified(method: ApproverMethod, verified: bool) -> None:
    assert method.is_verified is verified


def test_the_record_names_the_proof() -> None:
    assert _approver("priya", "approver", ApproverMethod.OIDC).describe() == "priya (oidc)"
    assert _approver("priya", "", ApproverMethod.LOCAL).describe() == "priya (local)"
