"""Unit — the human-approval gate, with fakes: a policy-allowed write is HELD, never forwarded
until a human approves; a deny, a timeout, or a vanished caller means it is never forwarded at all.
Every branch leaves a chained ledger record naming what happened and who decided.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest

from gatekeeper.domain.classify import ActionClassifier
from gatekeeper.domain.errors import ApprovalDenied
from gatekeeper.gateway.pipeline import ApprovalPolicy, GatewayPipeline
from gatekeeper.schemas.approval import ApprovalRequest
from gatekeeper.schemas.enums import ApprovalStatus, Verdict
from gatekeeper.schemas.ledger import LedgerEntry, VerifyResult
from gatekeeper.schemas.models import Decision, Principal, ToolCall, ToolResult

KEY = "k" * 64
ANNOTATIONS = {"demo": {"writes": ["write_file"], "reads": ["read_file"]}}


class Ledger:
    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []

    def append(self, entry: LedgerEntry) -> LedgerEntry:
        stored = entry.model_copy(update={"seq": len(self.entries) + 1, "prev_hash": "p"})
        self.entries.append(stored)
        return stored

    def read(self, *, limit: int = 100, principal: str | None = None) -> Sequence[LedgerEntry]:
        raise NotImplementedError

    def get(self, call_id: str) -> LedgerEntry | None:
        raise NotImplementedError

    def verify(self, *, expected_head: str | None = None) -> VerifyResult:
        raise NotImplementedError


class Upstream:
    def __init__(self) -> None:
        self.forwarded: list[ToolCall] = []

    async def forward(self, call: ToolCall) -> ToolResult:
        self.forwarded.append(call)
        return ToolResult(call_id=call.call_id, ok=True, summary="ok")


class Identity:
    def resolve(self, token: str) -> Principal:
        return Principal(id="alice", role={"admin-tok": "admin"}.get(token, "operator"))


class AllowAll:
    def evaluate(self, principal: Principal, call: ToolCall) -> Decision:
        return Decision(call_id=call.call_id, verdict=Verdict.ALLOW, reason="operator may write")


class Queue:
    """In-memory approval queue whose decisions arrive 'from another process' via decide()."""

    def __init__(self) -> None:
        self.requests: dict[str, ApprovalRequest] = {}

    def create(self, request: ApprovalRequest) -> ApprovalRequest:
        self.requests[request.id] = request
        return request

    def get(self, request_id: str) -> ApprovalRequest | None:
        return self.requests.get(request_id)

    def list_pending(self) -> Sequence[ApprovalRequest]:
        return [r for r in self.requests.values() if not r.is_final]

    def decide(
        self, request_id: str, status: ApprovalStatus, *, by: str, note: str = ""
    ) -> ApprovalRequest:
        current = self.requests[request_id]
        if current.is_final:
            raise RuntimeError("already decided")
        decided = current.model_copy(
            update={"status": status, "decided_by": by, "note": note, "arguments_preview": ""}
        )
        self.requests[request_id] = decided
        return decided


def _pipeline(
    ledger: Ledger, upstream: Upstream, queue: Queue | None, **policy: Any
) -> GatewayPipeline:
    return GatewayPipeline(
        identity=Identity(),
        classifier=ActionClassifier(name_patterns=["write*"], upstream_annotations=ANNOTATIONS),
        policy=AllowAll(),
        ledger=ledger,
        upstream=upstream,
        hmac_key=KEY,
        clock=lambda: "2026-09-08T12:00:00+00:00",
        approvals=queue,
        approval_policy=ApprovalPolicy(
            writes_require=True,
            timeout_s=policy.get("timeout_s", 5.0),
            poll_s=0.01,
            exempt_roles=frozenset(policy.get("exempt", ["admin"])),
        ),
    )


async def _call(pipe: GatewayPipeline, tool: str = "write_file", token: str = "tok") -> ToolResult:
    return await pipe.handle(
        token=token,
        upstream="demo",
        tool=tool,
        arguments={"path": "x", "content": "y"},
        call_id="c1",
    )


async def _decide_soon(queue: Queue, status: ApprovalStatus, by: str, note: str = "") -> None:
    while not queue.list_pending():  # noqa: ASYNC110 — the fake queue is sync; polling is the point
        await asyncio.sleep(0.005)
    request = queue.list_pending()[0]
    queue.decide(request.id, status, by=by, note=note)


async def test_approved_write_is_forwarded_with_a_chained_approval_record() -> None:
    ledger, upstream, queue = Ledger(), Upstream(), Queue()
    pipe = _pipeline(ledger, upstream, queue)

    decider = asyncio.create_task(_decide_soon(queue, ApprovalStatus.APPROVED, by="priya"))
    result = await _call(pipe)
    await decider

    assert result.ok and len(upstream.forwarded) == 1
    verdicts = [e.verdict for e in ledger.entries]
    assert verdicts == [Verdict.PENDING, Verdict.ALLOW, Verdict.ALLOW]  # held, approved, outcome
    assert "approved by priya" in ledger.entries[1].reason
    # the human saw the arguments; the ledger never stores them, and the queue blanks them after
    assert all("content" not in e.reason for e in ledger.entries)
    assert queue.requests[next(iter(queue.requests))].arguments_preview == ""


async def test_denied_write_is_never_forwarded_and_names_the_denier() -> None:
    ledger, upstream, queue = Ledger(), Upstream(), Queue()
    pipe = _pipeline(ledger, upstream, queue)

    decider = asyncio.create_task(
        _decide_soon(queue, ApprovalStatus.DENIED, by="priya", note="not your job")
    )
    with pytest.raises(ApprovalDenied, match="denied by priya"):
        await _call(pipe)
    await decider

    assert upstream.forwarded == []
    assert [e.verdict for e in ledger.entries] == [Verdict.PENDING, Verdict.DENY]
    assert "not your job" in ledger.entries[1].reason


async def test_no_decision_within_timeout_is_a_deny() -> None:
    ledger, upstream, queue = Ledger(), Upstream(), Queue()
    pipe = _pipeline(ledger, upstream, queue, timeout_s=0.05)

    with pytest.raises(ApprovalDenied, match="timed out"):
        await _call(pipe)

    assert upstream.forwarded == []
    assert [e.verdict for e in ledger.entries] == [Verdict.PENDING, Verdict.DENY]
    assert queue.list_pending() == []  # marked expired, not left dangling
    assert next(iter(queue.requests.values())).status is ApprovalStatus.EXPIRED


async def test_caller_that_goes_away_cancels_the_request_and_nothing_is_forwarded() -> None:
    ledger, upstream, queue = Ledger(), Upstream(), Queue()
    pipe = _pipeline(ledger, upstream, queue, timeout_s=10)

    task = asyncio.create_task(_call(pipe))
    while not queue.list_pending():  # noqa: ASYNC110 — see above
        await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert upstream.forwarded == []
    assert next(iter(queue.requests.values())).status is ApprovalStatus.CANCELLED
    # A late approval must not be possible: the request is final.
    with pytest.raises(RuntimeError):
        queue.decide(next(iter(queue.requests)), ApprovalStatus.APPROVED, by="late")


async def test_reads_are_never_held() -> None:
    ledger, upstream, queue = Ledger(), Upstream(), Queue()
    pipe = _pipeline(ledger, upstream, queue)
    result = await _call(pipe, tool="read_file")
    assert result.ok and queue.requests == {}
    assert [e.verdict for e in ledger.entries] == [Verdict.ALLOW, Verdict.ALLOW]


async def test_exempt_role_writes_go_straight_through_but_are_recorded() -> None:
    ledger, upstream, queue = Ledger(), Upstream(), Queue()
    pipe = _pipeline(ledger, upstream, queue)
    result = await _call(pipe, token="admin-tok")
    assert result.ok and queue.requests == {}
    assert [e.verdict for e in ledger.entries] == [Verdict.ALLOW, Verdict.ALLOW]


async def test_required_approval_without_a_queue_fails_closed() -> None:
    ledger, upstream = Ledger(), Upstream()
    pipe = _pipeline(ledger, upstream, None)
    from gatekeeper.domain.errors import PolicyDenied

    with pytest.raises(PolicyDenied, match="no approval queue"):
        await _call(pipe)
    assert upstream.forwarded == []
    assert [e.verdict for e in ledger.entries] == [Verdict.DENY]
