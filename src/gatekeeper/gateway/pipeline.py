"""The Policy Enforcement Point (PEP) — the governed pipeline every tool call passes through.

Chain (M1.2): ``identity -> classify -> POLICY(RBAC) -> AUDIT(decision) -> forward -> AUDIT``.
The Cedar ``PolicyEngine`` now decides allow/deny per (role x action x tool); an authenticated but
*unauthorized* call (e.g. a ``readonly`` role calling a write) is denied with a reason and recorded,
exactly like an unknown token — never forwarded.

Three invariants make the north-star ("no call slips past, all provable") literally true:
  * **Audit-before-act (ADR-003):** the decision entry (allow OR deny) is appended to the
    tamper-evident ledger BEFORE any upstream forward. If that append raises, we fail-closed.
  * **Fail-closed identity:** a bad token is denied AND audited, then raised (never forwarded).
  * **Fail-closed authorization:** a policy deny is audited, then raised — the forward never runs.

The forward is the only side effect and it lives inside ``handle``, after a recorded ALLOW, so a
call cannot be forwarded without first being authenticated, authorized, and audited (no bypass).
An allowed call yields two chained entries (committed-before-act decision + after-the-fact outcome);
a denied call yields one (the deny decision). See the feature doc.

The pipeline is SDK-free: it speaks only typed DTOs + ports, so it is fully unit-testable via fakes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from gatekeeper.adapters.ledger.hashchain import compute_payload_hash
from gatekeeper.domain.classify import ActionClassifier
from gatekeeper.domain.errors import IdentityError, PolicyDenied
from gatekeeper.infra.logging import get_logger
from gatekeeper.infra.tracing import ErrorReporter, default_reporter
from gatekeeper.ports.identity import IdentityResolver
from gatekeeper.ports.ledger import LedgerStore
from gatekeeper.ports.policy import PolicyEngine
from gatekeeper.ports.upstream import UpstreamClient
from gatekeeper.schemas.enums import ActionKind, Verdict
from gatekeeper.schemas.ledger import LedgerEntry
from gatekeeper.schemas.models import Principal, ToolCall, ToolResult

#: Recorded as the principal/role of a call whose token could not be authenticated.
UNAUTHENTICATED_PRINCIPAL = "<unauthenticated>"
UNAUTHENTICATED_ROLE = "<none>"


def _utc_now_iso() -> str:
    """Current time as a UTC ISO-8601 string (the ledger's ``ts`` contract)."""
    return datetime.now(UTC).isoformat()


class GatewayPipeline:
    """Govern + audit one tool call, then forward it. Deps injected (testable by construction)."""

    def __init__(
        self,
        *,
        identity: IdentityResolver,
        classifier: ActionClassifier,
        policy: PolicyEngine,
        ledger: LedgerStore,
        upstream: UpstreamClient,
        hmac_key: str,
        clock: Callable[[], str] = _utc_now_iso,
        reporter: ErrorReporter = default_reporter,
    ) -> None:
        self._identity = identity
        self._classifier = classifier
        self._policy = policy
        self._ledger = ledger
        self._upstream = upstream
        self._key = hmac_key
        self._clock = clock
        self._reporter = reporter
        self._log = get_logger("gatekeeper.gateway")

    async def handle(
        self, *, token: str, upstream: str, tool: str, arguments: dict[str, Any], call_id: str
    ) -> ToolResult:
        """Run the governed pipeline for one call. Raises ``IdentityError`` on an unknown token."""
        # 1. Identity — fail-closed: record the denied attempt, then refuse (no forward).
        try:
            principal = self._identity.resolve(token)
        except IdentityError as exc:
            self._record(
                call_id=call_id,
                principal=UNAUTHENTICATED_PRINCIPAL,
                role=UNAUTHENTICATED_ROLE,
                tenant="default",
                upstream=upstream,
                tool=tool,
                action=ActionKind.UNKNOWN,
                verdict=Verdict.DENY,
                reason=f"identity rejected: {exc}",
                arguments=arguments,
                result_summary="",
            )
            self._reporter.report(
                "call.denied.identity", call_id=call_id, upstream=upstream, tool=tool
            )
            self._log.warning(
                "call denied: unauthenticated",
                extra={"call_id": call_id, "upstream": upstream, "tool": tool},
            )
            raise

        # 2. Classify read/write (config-driven; enriches audit + feeds the policy action).
        action = self._classifier.classify(upstream, tool)
        call = ToolCall(
            call_id=call_id,
            upstream=upstream,
            tool=tool,
            arguments=arguments,
            action_kind=action,
        )

        # 3. Policy (RBAC, ADR-002) — Cedar decides allow/deny per (role x action x tool).
        #    The engine is fail-closed (any error -> DENY); default decision is deny.
        decision = self._policy.evaluate(principal, call)

        # A per-call recorder bound to the constants for this call, so the decision and outcome
        # entries can never drift on who/what/verdict — only reason + result_summary vary.
        audit = self._call_recorder(
            call_id=call_id,
            principal=principal,
            upstream=upstream,
            tool=tool,
            action=action,
            verdict=decision.verdict,
            arguments=arguments,
            risk=decision.risk,
        )

        # 4. AUDIT BEFORE ACT (ADR-003) — if this raises, we never forward (fail-closed).
        audit(reason=decision.reason, result_summary="")

        # 4b. Fail-closed authorization: a denied call is recorded (above) and then refused — the
        #     forward below is unreachable on a deny, so an unauthorized call has no side effect.
        if decision.verdict is Verdict.DENY:
            self._reporter.report(
                "call.denied.policy", call_id=call_id, upstream=upstream, tool=tool
            )
            self._log.warning(
                "call denied: policy",
                extra={
                    "call_id": call_id,
                    "principal": principal.id,
                    "role": principal.role,
                    "upstream": upstream,
                    "tool": tool,
                    "action": action.value,
                },
            )
            raise PolicyDenied(decision.reason)

        # 5. Forward to the real upstream (never raises; failures come back ok=False).
        result = await self._upstream.forward(call)

        # 6. AUDIT THE OUTCOME — a second chained entry completing the call's lifecycle.
        audit(
            reason="forward ok" if result.ok else "forward error",
            result_summary=result.summary,
        )
        if not result.ok:
            self._reporter.report(
                "call.forward.error", call_id=call_id, upstream=upstream, tool=tool
            )
        self._log.info(
            "call governed",
            extra={
                "call_id": call_id,
                "principal": principal.id,
                "upstream": upstream,
                "tool": tool,
                "action": action.value,
                "verdict": decision.verdict.value,
                "ok": result.ok,
            },
        )
        return result

    # --- internals ---------------------------------------------------------
    def _call_recorder(
        self,
        *,
        call_id: str,
        principal: Principal,
        upstream: str,
        tool: str,
        action: ActionKind,
        verdict: Verdict,
        arguments: dict[str, Any],
        risk: float | None,
    ) -> Callable[..., LedgerEntry]:
        """Bind the per-call constants once; the returned recorder only varies reason + summary."""

        def record(*, reason: str, result_summary: str) -> LedgerEntry:
            return self._record(
                call_id=call_id,
                principal=principal.id,
                role=principal.role,
                tenant=principal.tenant,
                upstream=upstream,
                tool=tool,
                action=action,
                verdict=verdict,
                reason=reason,
                arguments=arguments,
                result_summary=result_summary,
                risk=risk,
            )

        return record

    def _record(
        self,
        *,
        call_id: str,
        principal: str,
        role: str,
        tenant: str,
        upstream: str,
        tool: str,
        action: ActionKind,
        verdict: Verdict,
        reason: str,
        arguments: dict[str, Any],
        result_summary: str,
        risk: float | None = None,
    ) -> LedgerEntry:
        """Build + append one tamper-evident audit entry. Raises on append failure (fail-closed)."""
        entry = LedgerEntry(
            call_id=call_id,
            ts=self._clock(),
            tenant=tenant,
            principal=principal,
            role=role,
            upstream=upstream,
            tool=tool,
            action_kind=action,
            verdict=verdict,
            reason=reason,
            payload_hash=compute_payload_hash(self._key, arguments),
            result_summary=result_summary,
            risk=risk,
        )
        return self._ledger.append(entry)


__all__ = ["UNAUTHENTICATED_PRINCIPAL", "UNAUTHENTICATED_ROLE", "GatewayPipeline"]
