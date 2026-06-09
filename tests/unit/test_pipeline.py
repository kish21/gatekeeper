"""Unit tests for the GatewayPipeline (PEP) with fakes — the fail-closed governance invariants.

These pin the security-critical behaviors WITHOUT touching SQLite or a real MCP server:
  * audit-before-act ordering (ADR-003),
  * an unknown token is denied, audited, and NOT forwarded,
  * a ledger-append failure blocks the forward (no un-audited bypass),
  * raw arguments are never persisted (only a keyed payload_hash).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from gatekeeper.adapters.ledger.hashchain import compute_payload_hash
from gatekeeper.domain.classify import ActionClassifier
from gatekeeper.domain.errors import IdentityError, PolicyDenied
from gatekeeper.gateway.pipeline import UNAUTHENTICATED_PRINCIPAL, GatewayPipeline
from gatekeeper.schemas.enums import ActionKind, Verdict
from gatekeeper.schemas.ledger import LedgerEntry, VerifyResult
from gatekeeper.schemas.models import Decision, Principal, ToolCall, ToolResult

KEY = "k" * 64
PATTERNS = ["delete*", "write*"]
ANNOTATIONS = {"demo": {"writes": ["write_file"], "reads": ["read_file"]}}


class FakeIdentity:
    def __init__(self, mapping: dict[str, Principal]) -> None:
        self._m = mapping

    def resolve(self, token: str) -> Principal:
        principal = self._m.get(token)
        if principal is None:
            raise IdentityError("unknown token")
        return principal


class RecordingLedger:
    """Captures appends in order; can be told to fail on the Nth append (to test fail-closed)."""

    def __init__(self, events: list[tuple], *, fail_on: int | None = None) -> None:
        self.entries: list[LedgerEntry] = []
        self._events = events
        self._fail_on = fail_on
        self._n = 0

    def append(self, entry: LedgerEntry) -> LedgerEntry:
        self._n += 1
        if self._fail_on is not None and self._n == self._fail_on:
            raise RuntimeError("ledger unavailable")
        stored = entry.model_copy(
            update={"seq": self._n, "prev_hash": "p", "entry_hash": f"h{self._n}"}
        )
        self.entries.append(stored)
        self._events.append(("ledger", entry.verdict, entry.result_summary))
        return stored

    def read(self, *, limit: int = 100, principal: str | None = None) -> Sequence[LedgerEntry]:
        raise NotImplementedError

    def get(self, call_id: str) -> LedgerEntry | None:
        raise NotImplementedError

    def verify(self) -> VerifyResult:
        raise NotImplementedError


class FakePolicy:
    """A stand-in PolicyEngine: returns a fixed verdict so the pipeline is tested in isolation."""

    def __init__(self, verdict: Verdict = Verdict.ALLOW, reason: str = "ok") -> None:
        self._verdict = verdict
        self._reason = reason

    def evaluate(self, principal: Principal, call: ToolCall) -> Decision:
        return Decision(call_id=call.call_id, verdict=self._verdict, reason=self._reason)


class RecordingUpstream:
    def __init__(self, events: list[tuple], result: ToolResult) -> None:
        self._events = events
        self._result = result
        self.forwarded: list[ToolCall] = []

    async def forward(self, call: ToolCall) -> ToolResult:
        self._events.append(("forward", call.tool))
        self.forwarded.append(call)
        return self._result.model_copy(update={"call_id": call.call_id})


def _pipeline(
    events: list[tuple],
    *,
    upstream: RecordingUpstream,
    ledger: RecordingLedger,
    mapping: dict[str, Principal] | None = None,
    policy: FakePolicy | None = None,
) -> GatewayPipeline:
    return GatewayPipeline(
        identity=FakeIdentity(mapping or {"tok": Principal(id="alice", role="operator")}),
        classifier=ActionClassifier(name_patterns=PATTERNS, upstream_annotations=ANNOTATIONS),
        policy=policy or FakePolicy(),
        ledger=ledger,
        upstream=upstream,
        hmac_key=KEY,
        clock=lambda: "2026-06-09T12:00:00+00:00",
    )


async def test_allow_path_audits_before_and_after_forward() -> None:
    events: list[tuple] = []
    upstream = RecordingUpstream(events, ToolResult(call_id="x", ok=True, summary="2 entries"))
    ledger = RecordingLedger(events)
    pipe = _pipeline(events, upstream=upstream, ledger=ledger)

    result = await pipe.handle(
        token="tok", upstream="demo", tool="read_file", arguments={"path": "a"}, call_id="c1"
    )

    assert result.ok
    # decision entry committed BEFORE the forward; outcome entry AFTER (ADR-003).
    kinds = [e[0] for e in events]
    assert kinds == ["ledger", "forward", "ledger"]
    assert [e.verdict for e in ledger.entries] == [Verdict.ALLOW, Verdict.ALLOW]
    assert ledger.entries[0].result_summary == ""  # decision: no result yet
    assert ledger.entries[1].result_summary == "2 entries"  # outcome
    assert ledger.entries[0].action_kind is ActionKind.READ


async def test_write_tool_classified_write_in_audit() -> None:
    events: list[tuple] = []
    upstream = RecordingUpstream(events, ToolResult(call_id="x", ok=True, summary="wrote"))
    ledger = RecordingLedger(events)
    pipe = _pipeline(events, upstream=upstream, ledger=ledger)
    await pipe.handle(token="tok", upstream="demo", tool="write_file", arguments={}, call_id="c2")
    assert all(e.action_kind is ActionKind.WRITE for e in ledger.entries)


async def test_unknown_token_denied_audited_and_not_forwarded() -> None:
    events: list[tuple] = []
    upstream = RecordingUpstream(events, ToolResult(call_id="x", ok=True, summary="ok"))
    ledger = RecordingLedger(events)
    pipe = _pipeline(events, upstream=upstream, ledger=ledger, mapping={})  # no valid tokens

    with pytest.raises(IdentityError):
        await pipe.handle(
            token="bad", upstream="demo", tool="read_file", arguments={"path": "a"}, call_id="c3"
        )

    assert upstream.forwarded == []  # fail-closed: never forwarded
    assert len(ledger.entries) == 1  # the denied attempt IS recorded (no call slips past)
    denied = ledger.entries[0]
    assert denied.verdict is Verdict.DENY
    assert denied.principal == UNAUTHENTICATED_PRINCIPAL


async def test_ledger_append_failure_blocks_forward() -> None:
    events: list[tuple] = []
    upstream = RecordingUpstream(events, ToolResult(call_id="x", ok=True, summary="ok"))
    ledger = RecordingLedger(events, fail_on=1)  # the decision append fails
    pipe = _pipeline(events, upstream=upstream, ledger=ledger)

    with pytest.raises(RuntimeError, match="ledger unavailable"):
        await pipe.handle(
            token="tok", upstream="demo", tool="read_file", arguments={}, call_id="c4"
        )

    assert upstream.forwarded == []  # audit-before-act: no audit -> no forward


async def test_payload_hash_recorded_and_raw_args_never_persisted() -> None:
    events: list[tuple] = []
    upstream = RecordingUpstream(events, ToolResult(call_id="x", ok=True, summary="ok"))
    ledger = RecordingLedger(events)
    pipe = _pipeline(events, upstream=upstream, ledger=ledger)

    secret_args: dict[str, Any] = {"password": "hunter2", "path": "a"}
    await pipe.handle(
        token="tok", upstream="demo", tool="read_file", arguments=secret_args, call_id="c5"
    )

    entry = ledger.entries[0]
    assert entry.payload_hash == compute_payload_hash(KEY, secret_args)
    assert "hunter2" not in entry.model_dump_json()  # plaintext secret never stored


async def test_policy_deny_is_recorded_once_and_not_forwarded() -> None:
    events: list[tuple] = []
    upstream = RecordingUpstream(events, ToolResult(call_id="x", ok=True, summary="ok"))
    ledger = RecordingLedger(events)
    pipe = _pipeline(
        events,
        upstream=upstream,
        ledger=ledger,
        policy=FakePolicy(Verdict.DENY, "role 'readonly' may not write"),
    )

    with pytest.raises(PolicyDenied, match="readonly"):
        await pipe.handle(
            token="tok", upstream="demo", tool="write_file", arguments={"x": 1}, call_id="c6"
        )

    assert upstream.forwarded == []  # fail-closed authorization: a denied call is never forwarded
    assert len(ledger.entries) == 1  # exactly one entry — the recorded deny (no outcome entry)
    denied = ledger.entries[0]
    assert denied.verdict is Verdict.DENY
    assert denied.reason == "role 'readonly' may not write"
    assert denied.result_summary == ""  # deny is recorded before any forward, so no result
