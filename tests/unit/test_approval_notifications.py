"""Unit — a held write reaches a person, and a failing notifier never touches the decision.

Two independent claims:
  * the message says enough to act on (who, what, how long, where to go) without leaking more of
    the arguments than the desk itself shows;
  * notification is a signal channel, not a control. If Slack is down, the write still waits, the
    timeout still denies it, and the call is unaffected. A governance gateway that fails because
    a chat webhook is unreachable would be worse than one with no notifications at all.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from gatekeeper.domain.classify import ActionClassifier
from gatekeeper.domain.errors import ApprovalDenied
from gatekeeper.gateway.pipeline import ApprovalPolicy, GatewayPipeline
from gatekeeper.infra.notify import ApprovalNotifier, notifier_from_settings
from gatekeeper.schemas.approval import ApprovalRequest
from gatekeeper.schemas.enums import ApprovalStatus, Verdict
from gatekeeper.schemas.ledger import LedgerEntry
from gatekeeper.schemas.models import Decision, Principal, ToolCall, ToolResult

KEY = "k" * 64


def _request(**overrides: Any) -> ApprovalRequest:
    return ApprovalRequest(
        **{
            "id": "ab12cd34",
            "call_id": "call-1",
            "ts": "2026-09-08T10:00:00+00:00",
            "principal": "alice",
            "role": "operator",
            "upstream": "jira",
            "tool": "createJiraIssue",
            "arguments_preview": '{"summary": "Reset the billing job"}',
            **overrides,
        }
    )


# --- the message ------------------------------------------------------------------------------


def test_the_held_message_says_what_to_decide_and_where() -> None:
    notifier = ApprovalNotifier(url="https://hooks.example/x", desk_url="https://gk.corp/ui")
    text = notifier.held(_request(), timeout_s=300)["text"]

    assert "alice" in text and "operator" in text
    assert "jira:createJiraIssue" in text
    assert "Reset the billing job" in text  # enough context to judge it
    assert "ab12cd34" in text  # the id to decide it by
    assert "300s" in text  # how long they have
    assert "https://gk.corp/ui" in text  # where to go


def test_the_message_shows_no_more_than_the_desk_does() -> None:
    """The preview is already bounded and truncated; chat must not become a second leak path."""
    long_preview = '{"body": "' + "x" * 400 + '"}'
    text = ApprovalNotifier(url="https://hooks.example/x").held(
        _request(arguments_preview=long_preview), timeout_s=90
    )["text"]
    assert len(text) < 600
    assert "x" * 400 not in text


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ApprovalStatus.APPROVED, "approved"),
        (ApprovalStatus.DENIED, "denied"),
        (ApprovalStatus.EXPIRED, "timed out"),
        (ApprovalStatus.CANCELLED, "cancelled"),
    ],
)
def test_the_decision_message_closes_the_loop(status: ApprovalStatus, expected: str) -> None:
    """Every hold ends with an answer in the same place the question was asked."""
    outcome = _request(status=status, decided_by="priya", decided_method="oidc")
    message = ApprovalNotifier(url="https://hooks.example/x").decided(outcome)
    assert expected in message["text"]
    assert message["status"] == status.value
    if status is ApprovalStatus.APPROVED:
        assert "priya" in message["text"] and "oidc" in message["text"]


def test_no_webhook_means_no_delivery_and_no_error() -> None:
    silent = ApprovalNotifier()
    assert silent.enabled is False
    assert silent.post(silent.held(_request(), timeout_s=90)) is False
    silent.send(silent.held(_request(), timeout_s=90))  # must not raise


def test_the_approval_hook_falls_back_to_the_alert_hook() -> None:
    """One webhook is enough for a small deployment; two are allowed for a large one."""

    class _Settings:
        approval_webhook = ""
        alert_webhook = "https://hooks.example/ops"
        desk_url = "https://gk.corp/ui"

    assert notifier_from_settings(_Settings()).url == "https://hooks.example/ops"

    class _Both(_Settings):
        approval_webhook = "https://hooks.example/approvals"

    assert notifier_from_settings(_Both()).url == "https://hooks.example/approvals"


# --- notification must never affect the decision -----------------------------------------------


class _Identity:
    def resolve(self, token: str) -> Principal:
        return Principal(id="alice", role="operator")


class _Allow:
    def evaluate(self, principal: Principal, call: ToolCall) -> Decision:
        return Decision(call_id=call.call_id, verdict=Verdict.ALLOW, reason="operator may write")


class _Ledger:
    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []

    def append(self, entry: LedgerEntry) -> LedgerEntry:
        self.entries.append(entry)
        return entry


class _Upstream:
    def __init__(self) -> None:
        self.forwarded: list[ToolCall] = []

    async def forward(self, call: ToolCall) -> ToolResult:
        self.forwarded.append(call)
        return ToolResult(call_id=call.call_id, ok=True, summary="written")


class _Queue:
    """An approval queue nobody ever decides: the write will time out."""

    def __init__(self) -> None:
        self.requests: list[ApprovalRequest] = []

    def create(self, request: ApprovalRequest) -> ApprovalRequest:
        self.requests.append(request)
        return request

    def get(self, request_id: str) -> ApprovalRequest | None:
        return next((r for r in self.requests if r.id == request_id), None)

    def list_pending(self) -> list[ApprovalRequest]:
        return list(self.requests)

    def decide(
        self, request_id: str, status: ApprovalStatus, *, by: str, note: str = "", method: str = ""
    ) -> ApprovalRequest:
        current = self.get(request_id)
        assert current is not None
        decided = current.model_copy(
            update={"status": status, "decided_by": by, "note": note, "decided_method": method}
        )
        self.requests = [decided if r.id == request_id else r for r in self.requests]
        return decided


class _BrokenNotifier(ApprovalNotifier):
    """Every delivery raises — the worst a chat integration can do to us."""

    def post(self, payload: dict[str, Any]) -> bool:
        raise RuntimeError("slack is down")


@pytest.mark.asyncio
async def test_a_broken_notifier_does_not_break_the_hold() -> None:
    """The write is still held, still denied on timeout, and still recorded."""
    ledger, upstream, queue = _Ledger(), _Upstream(), _Queue()
    pipeline = GatewayPipeline(
        identity=_Identity(),
        classifier=ActionClassifier(
            name_patterns=["write*"], upstream_annotations={"demo": {"writes": ["write_file"]}}
        ),
        policy=_Allow(),
        ledger=ledger,
        upstream=upstream,
        hmac_key=KEY,
        approvals=queue,
        approval_policy=ApprovalPolicy(writes_require=True, timeout_s=0.2, poll_s=0.05),
        notifier=_BrokenNotifier(url="https://hooks.example/dead"),
    )

    with pytest.raises(ApprovalDenied, match="timed out"):
        await pipeline.handle(
            call_id="call-1", token="t", upstream="demo", tool="write_file", arguments={"path": "x"}
        )

    assert upstream.forwarded == [], "a notification failure must never release a write"
    assert [e.verdict for e in ledger.entries] == [Verdict.PENDING, Verdict.DENY]


@pytest.mark.asyncio
async def test_the_hold_announces_and_then_reports_the_outcome() -> None:
    """One message when the write starts waiting, one when it is resolved."""
    sent: list[dict[str, Any]] = []

    class _Recording(ApprovalNotifier):
        def post(self, payload: dict[str, Any]) -> bool:
            sent.append(payload)
            return True

    queue = _Queue()
    pipeline = GatewayPipeline(
        identity=_Identity(),
        classifier=ActionClassifier(
            name_patterns=["write*"], upstream_annotations={"demo": {"writes": ["write_file"]}}
        ),
        policy=_Allow(),
        ledger=_Ledger(),
        upstream=_Upstream(),
        hmac_key=KEY,
        approvals=queue,
        approval_policy=ApprovalPolicy(writes_require=True, timeout_s=5, poll_s=0.05),
        notifier=_Recording(url="https://hooks.example/x"),
    )

    call = asyncio.create_task(
        pipeline.handle(
            call_id="call-2",
            token="t",
            upstream="demo",
            tool="write_file",
            arguments={"path": "x"},
        )
    )
    # noqa: ASYNC110 — polling is the point: the hold is created inside the call under test, so
    # there is no event of ours to wait on without reaching into the pipeline's internals.
    while not queue.requests:  # noqa: ASYNC110
        await asyncio.sleep(0.01)
    queue.decide(queue.requests[0].id, ApprovalStatus.APPROVED, by="priya", method="oidc")
    await call

    # Delivery is deliberately fire-and-forget on a worker thread, so the call returns without
    # waiting for chat. Give that thread a moment before reading what it sent.
    for _ in range(200):
        if len(sent) >= 2:
            break
        await asyncio.sleep(0.01)

    assert [m["event"] for m in sent] == ["approval.held", "approval.decided"]
    assert sent[1]["decided_by"] == "priya"
