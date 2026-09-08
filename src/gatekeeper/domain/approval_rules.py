"""Who is allowed to decide a held write — pure rules, no I/O.

A gateway that records "approved by priya" is making a claim an auditor will test. Three things
have to hold for that claim to survive:

  * **The name was proven.** On anything reachable beyond loopback the approver presents a
    credential (a corporate login, or their own bearer token) that resolves to a named principal.
    A name typed into a form is an assertion, and it is recorded as one.
  * **The person is an approver.** Being able to reach the desk is not the same as being allowed
    to release a write; approving is its own privilege, granted by role.
  * **Nobody approves their own call.** Segregation of duties is the point of the hold. Without
    it, an operator with a desk tab open is an operator with no gate.

These are decided here, in one place, so the desk and the CLI cannot drift apart — and so the
rules can be tested without a browser, a database, or an identity provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gatekeeper.domain.errors import ApprovalRefused
from gatekeeper.schemas.approval import ApprovalRequest, Approver


@dataclass(frozen=True)
class ApproverRules:
    """Who may decide, from ``product.yaml`` ``approval`` (see ``approver_rules_from_config``)."""

    #: Roles allowed to decide. Empty = any authenticated identity may (the permissive default for
    #: a single-person install; a real deployment names its approver group).
    approver_roles: frozenset[str] = field(default_factory=frozenset)
    #: Refuse a decision by the same principal that made the call (segregation of duties).
    four_eyes: bool = True
    #: Allow `gatekeeper approve` from a shell on the gateway host. It is a real identity (that
    #: shell is privileged) but a weaker one, so a hardened deployment can turn it off and require
    #: a verified approver for every release.
    console_approvals: bool = True
    #: Refuse an unproven, typed-in name. Set for any bind reachable beyond loopback.
    require_verified: bool = False

    def check(self, request: ApprovalRequest, approver: Approver) -> None:
        """Raise ``ApprovalRefused`` unless ``approver`` may decide ``request``. Order matters:
        report the weakest link first, so the message names the thing to fix."""
        if approver.method.is_verified:
            self._check_role(approver)
        elif approver.is_console:
            if not self.console_approvals:
                raise ApprovalRefused(
                    "approvals from a shell on the gateway host are turned off here; decide at "
                    "the desk with your own login (approval.console_approvals: false)"
                )
        elif self.require_verified:
            raise ApprovalRefused(
                "this desk is reachable over the network, so a decision needs a verified "
                "identity: sign in, or present your own token — a typed name proves nothing"
            )

        if self.four_eyes and approver.id == request.principal:
            raise ApprovalRefused(
                f"{approver.id} made this call and cannot also approve it "
                "(four-eyes; approval.four_eyes: true)"
            )

    def _check_role(self, approver: Approver) -> None:
        if self.approver_roles and approver.role not in self.approver_roles:
            allowed = ", ".join(sorted(self.approver_roles))
            raise ApprovalRefused(
                f"role {approver.role!r} may not decide held writes (approver roles: {allowed})"
            )


def approver_rules_from_config(
    product: dict[str, object], *, require_verified: bool
) -> ApproverRules:
    """``product.yaml`` ``approval`` -> the rules. ``require_verified`` comes from the bind."""
    approval = product.get("approval") or {}
    if not isinstance(approval, dict):
        approval = {}
    return ApproverRules(
        approver_roles=frozenset(str(r) for r in (approval.get("approver_roles") or [])),
        four_eyes=bool(approval.get("four_eyes", True)),
        console_approvals=bool(approval.get("console_approvals", True)),
        require_verified=require_verified,
    )
