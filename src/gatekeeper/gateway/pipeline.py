"""The Policy Enforcement Point (PEP) — the governed pipeline every tool call passes through.

Chain: ``identity -> classify -> POLICY -> [HOLD for human approval] -> AUDIT -> forward -> AUDIT``.

A write the policy allows can still be HELD: when approval is configured, the call is recorded as
``pending``, an approval request is queued, and the pipeline waits for a human to run
``gatekeeper approve`` or ``gatekeeper deny`` (or for the timeout). Approved -> an ``allow`` entry
naming the approver, then the forward. Denied, timed out, or cancelled -> a ``deny`` entry, never
forwarded. Reads are never held.
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

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from gatekeeper.adapters.ledger.hashchain import compute_payload_hash
from gatekeeper.domain.classify import ActionClassifier
from gatekeeper.domain.errors import ApprovalDenied, IdentityError, PolicyDenied
from gatekeeper.infra.alerts import DenySpikeDetector, WebhookAlerter
from gatekeeper.infra.logging import get_logger
from gatekeeper.infra.metrics import GatewayMetrics, default_metrics
from gatekeeper.infra.tracing import ErrorReporter, default_reporter
from gatekeeper.ports.approval import ApprovalQueue
from gatekeeper.ports.identity import IdentityResolver
from gatekeeper.ports.ledger import LedgerStore
from gatekeeper.ports.policy import PolicyEngine
from gatekeeper.ports.upstream import UpstreamClient
from gatekeeper.schemas.approval import ARGUMENTS_PREVIEW_MAX, ApprovalRequest
from gatekeeper.schemas.enums import ActionKind, ApprovalStatus, Verdict
from gatekeeper.schemas.ledger import LedgerEntry
from gatekeeper.schemas.models import Decision, Principal, ToolCall, ToolResult

#: Recorded as the principal/role of a call whose token could not be authenticated.
UNAUTHENTICATED_PRINCIPAL = "<unauthenticated>"
UNAUTHENTICATED_ROLE = "<none>"


@dataclass(frozen=True)
class ApprovalPolicy:
    """When a policy-allowed call is still held for a human (from ``product.yaml`` ``approval``)."""

    writes_require: bool = False
    timeout_s: float = 90.0
    exempt_roles: frozenset[str] = field(default_factory=frozenset)
    poll_s: float = 0.5

    def applies(self, role: str, action: ActionKind) -> bool:
        return self.writes_require and action is ActionKind.WRITE and role not in self.exempt_roles


def _utc_now_iso() -> str:
    """Current time as a UTC ISO-8601 string (the ledger's ``ts`` contract)."""
    return datetime.now(UTC).isoformat()


def _decider(outcome: ApprovalRequest) -> str:
    """The approver as the ledger names them: who, and how that name was proven.

    An auditor reading "approved by priya (oidc)" three years from now can tell that priya signed
    in with the company login; "(local)" says a name was typed into a loopback page. Recording the
    proof next to the name is what stops the audit trail from over-claiming.
    """
    method = f", {outcome.decided_method}" if outcome.decided_method else ""
    return f"{outcome.decided_by}{method}"


def _approval_deny_reason(outcome: ApprovalRequest, timeout_s: float) -> str:
    if outcome.status is ApprovalStatus.DENIED:
        note = f": {outcome.note}" if outcome.note else ""
        return f"denied by {_decider(outcome)} (request {outcome.id}){note}"
    if outcome.status is ApprovalStatus.EXPIRED:
        return f"approval timed out after {timeout_s:g}s (request {outcome.id})"
    return f"approval {outcome.status.value} (request {outcome.id})"


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
        metrics: GatewayMetrics = default_metrics,
        deny_detector: DenySpikeDetector | None = None,
        alerter: WebhookAlerter | None = None,
        approvals: ApprovalQueue | None = None,
        approval_policy: ApprovalPolicy | None = None,
    ) -> None:
        self._identity = identity
        self._classifier = classifier
        self._policy = policy
        self._ledger = ledger
        self._upstream = upstream
        self._key = hmac_key
        self._clock = clock
        self._reporter = reporter
        self._metrics = metrics
        self._deny_detector = deny_detector
        self._alerter = alerter
        self._approvals = approvals
        self._approval_policy = approval_policy or ApprovalPolicy()
        self._log = get_logger("gatekeeper.gateway")

    async def handle(
        self, *, token: str, upstream: str, tool: str, arguments: dict[str, Any], call_id: str
    ) -> ToolResult:
        """Run the governed pipeline for one call. Raises ``IdentityError`` on an unknown token."""
        # Governance-overhead timing (M3.4): everything EXCEPT the upstream forward — the same
        # quantity the /eval bench measures, so the live p95 gauge and the bench agree.
        t_start = time.perf_counter()
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
            self._metrics.record_identity_deny()
            self._metrics.record_call(Verdict.DENY.value, time.perf_counter() - t_start)
            self._note_deny(call_id=call_id, upstream=upstream, tool=tool, kind="identity")
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
        # entries can never drift on who/what — only verdict, reason + result_summary vary.
        audit = self._call_recorder(
            call_id=call_id,
            principal=principal,
            upstream=upstream,
            tool=tool,
            action=action,
            arguments=arguments,
            risk=decision.risk,
        )

        # 4. AUDIT BEFORE ACT — if this raises, we never forward (fail-closed).
        held = decision.verdict is Verdict.ALLOW and self._approval_policy.applies(
            principal.role, action
        )
        if held and self._approvals is None:
            # Approval is required but there is no queue to hold the call in: fail closed.
            decision = Decision(
                call_id=call_id,
                verdict=Verdict.DENY,
                reason="write requires human approval but no approval queue is configured",
            )
            held = False
        audit(
            verdict=Verdict.PENDING if held else decision.verdict,
            reason=(
                f"write held for human approval ({decision.reason})" if held else decision.reason
            ),
            result_summary="",
        )

        # 4b. Fail-closed authorization: a denied call is recorded (above) and then refused — the
        #     forward below is unreachable on a deny, so an unauthorized call has no side effect.
        if decision.verdict is Verdict.DENY:
            self._reporter.report(
                "call.denied.policy", call_id=call_id, upstream=upstream, tool=tool
            )
            self._metrics.record_call(Verdict.DENY.value, time.perf_counter() - t_start)
            self._note_deny(call_id=call_id, upstream=upstream, tool=tool, kind="policy")
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

        # 4c. HOLD: a human decides. Approved -> a chained ALLOW entry naming the approver, then
        #     the forward. Anything else -> a chained DENY entry, and the forward never runs.
        if held:
            assert self._approvals is not None
            try:
                outcome = await self._hold_for_approval(
                    call_id=call_id,
                    principal=principal,
                    upstream=upstream,
                    tool=tool,
                    arguments=arguments,
                )
            except asyncio.CancelledError:
                # The caller went away while waiting. The ledger must still close the call:
                # a chained DENY, so nothing is left looking "pending" forever.
                audit(
                    verdict=Verdict.DENY,
                    reason="approval cancelled: the caller disconnected while waiting",
                    result_summary="",
                )
                raise
            if outcome.status is ApprovalStatus.APPROVED:
                audit(
                    verdict=Verdict.ALLOW,
                    reason=f"approved by {_decider(outcome)} (request {outcome.id})",
                    result_summary="",
                )
            else:
                reason = _approval_deny_reason(outcome, self._approval_policy.timeout_s)
                audit(verdict=Verdict.DENY, reason=reason, result_summary="")
                self._reporter.report(
                    "call.denied.approval", call_id=call_id, upstream=upstream, tool=tool
                )
                self._metrics.record_call(Verdict.DENY.value, time.perf_counter() - t_start)
                self._note_deny(call_id=call_id, upstream=upstream, tool=tool, kind="approval")
                self._log.warning(
                    "call denied: approval",
                    extra={"call_id": call_id, "request": outcome.id, "status": outcome.status},
                )
                raise ApprovalDenied(reason)

        # 5. Forward to the real upstream (never raises; failures come back ok=False).
        #    The forward itself is upstream time, not governance overhead — pause the clock.
        t_pre_forward = time.perf_counter()
        result = await self._upstream.forward(call)
        t_post_forward = time.perf_counter()

        # 6. AUDIT THE OUTCOME — a further chained entry completing the call's lifecycle.
        audit(
            verdict=Verdict.ALLOW,
            reason="forward ok" if result.ok else "forward error",
            result_summary=result.summary,
        )
        overhead = (t_pre_forward - t_start) + (time.perf_counter() - t_post_forward)
        self._metrics.record_call(Verdict.ALLOW.value, overhead)
        if not result.ok:
            self._metrics.record_forward_error()
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
    async def _hold_for_approval(
        self,
        *,
        call_id: str,
        principal: Principal,
        upstream: str,
        tool: str,
        arguments: dict[str, Any],
    ) -> ApprovalRequest:
        """Queue the request and wait for a final status: decided by a human, expired, or
        cancelled because the caller went away. Never forwards."""
        assert self._approvals is not None
        policy = self._approval_policy
        preview = json.dumps(arguments, sort_keys=True, default=str)[:ARGUMENTS_PREVIEW_MAX]
        request = self._approvals.create(
            ApprovalRequest(
                id=uuid.uuid4().hex[:8],
                call_id=call_id,
                ts=self._clock(),
                principal=principal.id,
                role=principal.role,
                upstream=upstream,
                tool=tool,
                arguments_preview=preview,
            )
        )
        self._log.warning(
            "write held for human approval",
            extra={
                "request": request.id,
                "principal": principal.id,
                "tool": f"{upstream}:{tool}",
                "decide_with": f"gatekeeper approve {request.id}  |  gatekeeper deny {request.id}",
                "timeout_s": policy.timeout_s,
            },
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + policy.timeout_s
        try:
            while True:
                current = self._approvals.get(request.id)
                if current is not None and current.is_final:
                    return current
                if loop.time() >= deadline:
                    return self._approvals.decide(
                        request.id,
                        ApprovalStatus.EXPIRED,
                        by="gateway",
                        note=f"no decision within {policy.timeout_s:g}s",
                    )
                await asyncio.sleep(policy.poll_s)
        except asyncio.CancelledError:
            # The caller stopped waiting: a late approval must never execute a write nobody is
            # watching. Best-effort mark; if the request was decided meanwhile, keep that record.
            try:
                self._approvals.decide(
                    request.id,
                    ApprovalStatus.CANCELLED,
                    by="gateway",
                    note="caller disconnected while waiting",
                )
            except Exception as exc:  # noqa: BLE001 — already decided or store gone
                self._log.debug("could not mark request cancelled", extra={"error": str(exc)})
            raise

    def _note_deny(self, *, call_id: str, upstream: str, tool: str, kind: str) -> None:
        """Feed the deny-spike detector; on a NEW breach, fire the alert OFF the hot path.

        Fail-safe by construction: the webhook posts from a worker thread (fire-and-forget),
        so a slow/down alert receiver can never block or fail a governed call.
        """
        if self._deny_detector is None or self._alerter is None or not self._alerter.enabled:
            return
        if not self._deny_detector.record_deny():
            return
        detail = {
            "kind": kind,
            "denies_in_window": self._deny_detector.current_count,
            "last_call_id": call_id,
            "last_target": f"{upstream}:{tool}",
        }
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # sync/test context: deliver inline (still never raises)
            self._alerter.fire("deny_spike", detail)
            return
        loop.run_in_executor(None, self._alerter.fire, "deny_spike", detail)

    def _call_recorder(
        self,
        *,
        call_id: str,
        principal: Principal,
        upstream: str,
        tool: str,
        action: ActionKind,
        arguments: dict[str, Any],
        risk: float | None,
    ) -> Callable[..., LedgerEntry]:
        """Bind the per-call constants once; the recorder varies verdict, reason and summary."""

        def record(*, verdict: Verdict, reason: str, result_summary: str) -> LedgerEntry:
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


__all__ = ["UNAUTHENTICATED_PRINCIPAL", "UNAUTHENTICATED_ROLE", "ApprovalPolicy", "GatewayPipeline"]
