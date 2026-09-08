"""Integration — the approval queue in SQLite, decided from ANOTHER PROCESS while the gateway waits.

This is the real shape: `gatekeeper serve` holds the write in one process; a person runs
`gatekeeper approve <id>` in a terminal. The gateway must see that commit on its next poll, the
ledger must chain the hold, the approval (naming the approver) and the outcome, and `verify` must
still be clean.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from gatekeeper.adapters.approval.sqlite import ApprovalStateError, SqliteApprovalQueue
from gatekeeper.adapters.ledger.factory import migrate
from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.cli import app as cli_app
from gatekeeper.config import loader
from gatekeeper.db.base import create_ledger_engine
from gatekeeper.domain.classify import ActionClassifier
from gatekeeper.domain.errors import ApprovalDenied
from gatekeeper.gateway.pipeline import ApprovalPolicy, GatewayPipeline
from gatekeeper.schemas.approval import ApprovalRequest
from gatekeeper.schemas.enums import ApprovalStatus, Verdict
from gatekeeper.schemas.models import Decision, Principal, ToolCall, ToolResult

KEY = "k" * 64
runner = CliRunner()


class _Identity:
    def resolve(self, token: str) -> Principal:
        return Principal(id="alice", role="operator")


class _Allow:
    def evaluate(self, principal: Principal, call: ToolCall) -> Decision:
        return Decision(call_id=call.call_id, verdict=Verdict.ALLOW, reason="operator may write")


class _Upstream:
    def __init__(self) -> None:
        self.forwarded: list[ToolCall] = []

    async def forward(self, call: ToolCall) -> ToolResult:
        self.forwarded.append(call)
        return ToolResult(call_id=call.call_id, ok=True, summary="ok: written")


def _gateway(db: str, upstream: _Upstream, timeout_s: float = 20) -> GatewayPipeline:
    engine = create_ledger_engine(db)
    return GatewayPipeline(
        identity=_Identity(),
        classifier=ActionClassifier(
            name_patterns=["write*"], upstream_annotations={"demo": {"writes": ["write_file"]}}
        ),
        policy=_Allow(),
        ledger=SqliteLedgerStore(Session(engine), KEY),
        upstream=upstream,
        hmac_key=KEY,
        approvals=SqliteApprovalQueue(Session(engine)),
        approval_policy=ApprovalPolicy(writes_require=True, timeout_s=timeout_s, poll_s=0.05),
    )


def _decide_in_another_process(db: str, status: str, by: str) -> None:  # child process
    import time

    from sqlalchemy.orm import Session as _S

    from gatekeeper.adapters.approval.sqlite import SqliteApprovalQueue as _Q
    from gatekeeper.db.base import create_ledger_engine as _E
    from gatekeeper.schemas.enums import ApprovalStatus as _St

    queue = _Q(_S(_E(db)))
    for _ in range(200):
        pending = queue.list_pending()
        if pending:
            queue.decide(pending[0].id, _St(status), by=by, note="from another process")
            return
        time.sleep(0.05)
    raise SystemExit("never saw a pending request")


@pytest.mark.parametrize("status", ["approved", "denied"])
async def test_decision_from_another_process_is_honoured(tmp_path: Path, status: str) -> None:
    db = str(tmp_path / "audit.db")
    migrate(db)
    upstream = _Upstream()
    gateway = _gateway(db, upstream)

    child = mp.get_context("spawn").Process(
        target=_decide_in_another_process, args=(db, status, "priya")
    )
    child.start()
    try:
        call = gateway.handle(
            token="t", upstream="demo", tool="write_file", arguments={"path": "a"}, call_id="c1"
        )
        if status == "approved":
            result = await asyncio.wait_for(call, 30)
            assert result.ok and len(upstream.forwarded) == 1
            expected = [Verdict.PENDING, Verdict.ALLOW, Verdict.ALLOW]
        else:
            with pytest.raises(ApprovalDenied, match="denied by priya"):
                await asyncio.wait_for(call, 30)
            assert upstream.forwarded == []
            expected = [Verdict.PENDING, Verdict.DENY]
    finally:
        child.join(30)
    assert child.exitcode == 0

    ledger = SqliteLedgerStore(Session(create_ledger_engine(db)), KEY)
    entries = list(reversed(ledger.read(limit=10)))
    assert [e.verdict for e in entries] == expected
    assert "priya" in entries[1].reason
    assert ledger.verify().ok


def test_a_decision_cannot_be_changed_or_repeated(tmp_path: Path) -> None:
    db = str(tmp_path / "audit.db")
    migrate(db)
    queue = SqliteApprovalQueue(Session(create_ledger_engine(db)))
    queue.create(
        ApprovalRequest(
            id="abc12345",
            call_id="c",
            ts="t",
            principal="alice",
            role="operator",
            upstream="demo",
            tool="write_file",
            arguments_preview='{"path": "a"}',
        )
    )
    decided = queue.decide("abc12345", ApprovalStatus.DENIED, by="priya")
    assert decided.arguments_preview == ""  # raw args are dropped once decided
    with pytest.raises(ApprovalStateError, match="already denied"):
        queue.decide("abc12345", ApprovalStatus.APPROVED, by="mallory")
    with pytest.raises(ApprovalStateError, match="no approval request"):
        queue.decide("nope", ApprovalStatus.APPROVED, by="x")


def test_cli_pending_approve_deny(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "audit.db"
    migrate(str(db))
    queue = SqliteApprovalQueue(Session(create_ledger_engine(str(db))))
    for rid in ("aaaa0001", "bbbb0002"):
        queue.create(
            ApprovalRequest(
                id=rid,
                call_id="c-" + rid,
                ts="2026-09-08T12:00:00+00:00",
                principal="alice",
                role="operator",
                upstream="demo",
                tool="write_file",
                arguments_preview='{"path": "notes.txt"}',
            )
        )
    monkeypatch.setenv("GATEKEEPER_HMAC_KEY", KEY)
    monkeypatch.setenv("GATEKEEPER_LEDGER_PATH", str(db))
    monkeypatch.setenv("GATEKEEPER_CONFIG_DIR", str(Path("config").resolve()))
    loader.get_settings.cache_clear()

    listed = runner.invoke(cli_app.app, ["pending"])
    assert listed.exit_code == 0, listed.output
    assert "aaaa0001" in listed.output and "notes.txt" in listed.output

    ok = runner.invoke(cli_app.app, ["approve", "aaaa0001", "--by", "priya"])
    assert ok.exit_code == 0 and "APPROVED" in ok.output and "priya" in ok.output
    no = runner.invoke(cli_app.app, ["deny", "bbbb0002", "--by", "priya", "--reason", "nope"])
    assert no.exit_code == 0 and "DENIED" in no.output

    again = runner.invoke(cli_app.app, ["approve", "aaaa0001"])
    assert again.exit_code == 1 and "already approved" in again.output
    assert "(nothing waiting" in runner.invoke(cli_app.app, ["pending"]).output


def test_windows_console_safe_pending_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "audit.db"
    migrate(str(db))
    monkeypatch.setenv("GATEKEEPER_HMAC_KEY", KEY)
    monkeypatch.setenv("GATEKEEPER_LEDGER_PATH", str(db))
    monkeypatch.setenv("GATEKEEPER_CONFIG_DIR", str(Path("config").resolve()))
    loader.get_settings.cache_clear()
    runner.invoke(cli_app.app, ["pending"]).output.encode("cp1252")
