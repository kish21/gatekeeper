"""Who is at the desk — resolving the approver from the request, with the proof.

The desk takes one credential, in the ordinary place (``Authorization: Bearer …``), and works out
what it is:

  * **a personal identity** — an OIDC token from the company login, or a bearer token that
    ``identities.yaml`` maps to a named principal and role. The gateway already resolves exactly
    these to identify *callers*, so the desk reuses that resolver rather than inventing a second,
    weaker notion of identity. A decision made this way names a person who proved it.
  * **the shared desk token** (``GATEKEEPER_UI_TOKEN``) — proof that you are allowed to *see* the
    desk, and nothing at all about who you are. It opens the page; on a network-facing desk it
    does not release writes.
  * **nothing**, on a loopback desk with no identity configured — the laptop case, where the
    person at the keyboard is the person who installed it. The name they type is recorded as
    typed, marked ``local``, and an auditor can see exactly how much that is worth.

The rule this file exists to enforce: a name that was not proven is never silently written into
the audit trail as though it had been.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gatekeeper.config.loader import ConfigError
from gatekeeper.domain.errors import IdentityError
from gatekeeper.infra.logging import get_logger
from gatekeeper.ports.identity import IdentityResolver
from gatekeeper.schemas.approval import Approver
from gatekeeper.schemas.enums import ApproverMethod

_log = get_logger("gatekeeper.ui.identity")


@dataclass(frozen=True)
class DeskIdentity:
    """The identity source the desk authenticates approvers against (from the gateway's config)."""

    resolver: IdentityResolver | None
    #: How a name this resolver returns was proven — the corporate login, or a personal token.
    method: ApproverMethod = ApproverMethod.TOKEN

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> DeskIdentity:
        """Build the desk's identity source from the SAME configuration the gateway authenticates
        callers with. A misconfigured provider is not a reason to fall back to trusting a typed
        name, so a failure here leaves the desk with no resolver (and, beyond loopback, no way to
        approve) rather than with a weaker one."""
        from gatekeeper.gateway.factory import build_identity

        kind = str((config.get("platform") or {}).get("adapters", {}).get("identity", ""))
        try:
            resolver = build_identity(config)
        except ConfigError as exc:
            _log.warning("desk identity unavailable", extra={"error": str(exc)})
            return cls(resolver=None)
        method = ApproverMethod.OIDC if kind == "oidc" else ApproverMethod.TOKEN
        return cls(resolver=resolver, method=method)

    def resolve(self, credential: str) -> Approver | None:
        """The approver this credential proves, or ``None`` if it proves no identity."""
        if not credential or self.resolver is None:
            return None
        try:
            principal = self.resolver.resolve(credential)
        except IdentityError:
            return None
        return Approver(id=principal.id, role=principal.role, method=self.method)


def bearer_credential(headers: Any) -> str:
    """The bearer value from an ``Authorization`` header, or ``""``."""
    supplied = headers.get("authorization", "") or ""
    scheme, _, value = supplied.partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


def local_approver(typed_name: str) -> Approver:
    """A name typed on a loopback desk: recorded, and recorded as unproven."""
    return Approver(id=typed_name, role="", method=ApproverMethod.LOCAL)
