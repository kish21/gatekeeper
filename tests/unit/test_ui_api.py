"""Unit — the web desk's API: it reads and writes the same queue and ledger as the CLI, and it
is gated by a token whenever one is configured."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gatekeeper.adapters.approval.sqlite import SqliteApprovalQueue
from gatekeeper.adapters.ledger.factory import migrate
from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.config import loader
from gatekeeper.db.base import create_ledger_engine
from gatekeeper.schemas.approval import ApprovalRequest
from gatekeeper.schemas.enums import ActionKind, Verdict
from gatekeeper.schemas.ledger import LedgerEntry
from gatekeeper.ui import create_ui_app

KEY = "k" * 64


def _entry(call_id: str, verdict: Verdict, reason: str, tool: str = "write_file") -> LedgerEntry:
    return LedgerEntry(
        call_id=call_id,
        ts="2026-09-08T12:00:00+00:00",
        principal="alice",
        role="operator",
        upstream="demo-files",
        tool=tool,
        action_kind=ActionKind.WRITE,
        verdict=verdict,
        reason=reason,
        payload_hash="a" * 64,
    )


@pytest.fixture
def desk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str]:
    db = str(tmp_path / "audit.db")
    migrate(db)
    monkeypatch.setenv("GATEKEEPER_HMAC_KEY", KEY)
    monkeypatch.setenv("GATEKEEPER_LEDGER_PATH", db)
    monkeypatch.setenv("GATEKEEPER_CONFIG_DIR", str(Path("config").resolve()))
    loader.get_settings.cache_clear()

    store = SqliteLedgerStore(Session(create_ledger_engine(db)), KEY)
    store.append(_entry("call-1", Verdict.PENDING, "write held for human approval"))
    store.append(_entry("call-1", Verdict.DENY, "denied by priya (request r1): nope"))
    store.append(_entry("call-2", Verdict.ALLOW, "ok", tool="read_file"))
    store.close()
    queue = SqliteApprovalQueue(Session(create_ledger_engine(db)))
    queue.create(
        ApprovalRequest(
            id="r2000001",
            call_id="call-3",
            ts="2026-09-08T12:01:00+00:00",
            principal="alice",
            role="operator",
            upstream="jira",
            tool="createJiraIssue",
            arguments_preview='{"summary": "x"}',
        )
    )
    queue.close()

    def open_store() -> SqliteLedgerStore:
        return SqliteLedgerStore(Session(create_ledger_engine(db)), KEY)

    return TestClient(create_ui_app(open_store)), db


def test_page_and_summary(desk: tuple[TestClient, str]) -> None:
    client, _ = desk
    assert "GateKeeper" in client.get("/ui").text
    s = client.get("/ui/api/summary").json()
    assert s["pending"] == 1 and s["calls"] == 2
    assert s["by_verdict"] == {"allow": 1, "deny": 1, "pending": 0}


def test_activity_groups_a_call_with_its_final_verdict(desk: tuple[TestClient, str]) -> None:
    client, _ = desk
    calls = {c["call_id"]: c for c in client.get("/ui/api/activity").json()}
    assert calls["call-1"]["final_verdict"] == "deny"
    assert [e["verdict"] for e in calls["call-1"]["entries"]] == ["pending", "deny"]
    assert calls["call-2"]["final_verdict"] == "allow"
    detail = client.get("/ui/api/calls/call-1").json()
    assert len(detail["entries"]) == 2


def test_decide_from_the_desk_writes_the_same_queue(desk: tuple[TestClient, str]) -> None:
    client, db = desk
    assert [r["id"] for r in client.get("/ui/api/pending").json()] == ["r2000001"]
    r = client.post(
        "/ui/api/pending/r2000001/decision",
        json={"status": "denied", "by": "priya", "note": "not now"},
    )
    assert r.status_code == 200 and r.json()["decided_by"] == "priya"
    assert client.get("/ui/api/pending").json() == []
    # the CLI and the gateway see the same decision
    queue = SqliteApprovalQueue(Session(create_ledger_engine(db)))
    got = queue.get("r2000001")
    assert got is not None and got.status.value == "denied" and got.arguments_preview == ""
    # and it cannot be changed
    again = client.post(
        "/ui/api/pending/r2000001/decision", json={"status": "approved", "by": "mallory"}
    )
    assert again.status_code == 409


def test_decision_requires_a_final_status_and_a_name(desk: tuple[TestClient, str]) -> None:
    client, _ = desk
    assert (
        client.post(
            "/ui/api/pending/r2000001/decision", json={"status": "pending", "by": "p"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/ui/api/pending/r2000001/decision", json={"status": "approved", "by": ""}
        ).status_code
        == 422
    )


def test_verify_and_servers(desk: tuple[TestClient, str]) -> None:
    client, _ = desk
    v = client.post("/ui/api/verify").json()
    assert v["ok"] and v["checked"] == 3
    servers = client.get("/ui/api/servers").json()
    names = {s["name"] for s in servers}
    assert {"demo-files", "sharepoint", "jira", "github", "database", "mail", "_policy"} <= names
    jira = next(s for s in servers if s["name"] == "jira")
    assert jira["twin"] and "createJiraIssue" in jira["writes"]


def test_token_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = str(tmp_path / "audit.db")
    migrate(db)
    monkeypatch.setenv("GATEKEEPER_HMAC_KEY", KEY)
    monkeypatch.setenv("GATEKEEPER_CONFIG_DIR", str(Path("config").resolve()))
    loader.get_settings.cache_clear()
    client = TestClient(
        create_ui_app(
            lambda: SqliteLedgerStore(Session(create_ledger_engine(db)), KEY), token="s3cret"
        )
    )
    assert client.get("/ui").status_code == 200  # the page itself loads and asks for the token
    assert client.get("/ui/api/pending").status_code == 401
    assert (
        client.get("/ui/api/pending", headers={"Authorization": "Bearer wrong"}).status_code == 401
    )
    assert (
        client.get("/ui/api/pending", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    )
