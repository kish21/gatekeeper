"""Policy port: (principal, call) -> Decision. Implemented by adapters.policy.cedar."""

from __future__ import annotations

from typing import Protocol

from gatekeeper.schemas.models import Decision, Principal, ToolCall


class PolicyEngine(Protocol):
    """Evaluate whether a principal may make a call.

    Contract: deterministic; on any evaluation error the caller treats it as DENY (fail-closed).
    """

    def evaluate(self, principal: Principal, call: ToolCall) -> Decision: ...
