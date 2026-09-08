"""Unit — the web desk's API: it reads and writes the same queue and ledger as the CLI, it is
gated by a token whenever one is configured, and it will not let an unproven name release a write
on a desk that anyone on the network can reach."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gatekeeper.adapters.approval.sql import SqlApprovalQueue
from gatekeeper.adapters.ledger.factory import migrate
from gatekeeper.adapters.ledger.sql import SqlLedgerStore
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

    store = SqlLedgerStore(Session(create_ledger_engine(db)), KEY)
    store.append(_entry("call-1", Verdict.PENDING, "write held for human approval"))
    store.append(_entry("call-1", Verdict.DENY, "denied by priya (request r1): nope"))
    store.append(_entry("call-2", Verdict.ALLOW, "ok", tool="read_file"))
    store.close()
    queue = SqlApprovalQueue(Session(create_ledger_engine(db)))
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

    def open_store() -> SqlLedgerStore:
        return SqlLedgerStore(Session(create_ledger_engine(db)), KEY)

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
    queue = SqlApprovalQueue(Session(create_ledger_engine(db)))
    got = queue.get("r2000001")
    assert got is not None and got.status.value == "denied" and got.arguments_preview == ""
    # and it cannot be changed
    again = client.post(
        "/ui/api/pending/r2000001/decision", json={"status": "approved", "by": "mallory"}
    )
    assert again.status_code == 409


def test_decision_requires_a_final_status_and_a_decider(desk: tuple[TestClient, str]) -> None:
    client, _ = desk
    assert (
        client.post(
            "/ui/api/pending/r2000001/decision", json={"status": "pending", "by": "p"}
        ).status_code
        == 400
    )
    # Nobody signed in and no name given: there would be no one to record, so nothing is decided.
    assert (
        client.post(
            "/ui/api/pending/r2000001/decision", json={"status": "approved", "by": ""}
        ).status_code
        == 400
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
            lambda: SqlLedgerStore(Session(create_ledger_engine(db)), KEY), token="s3cret"
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


# --- a desk anyone on the network can reach ----------------------------------------------------
# The identities below are the repo's demo tokens: `priya` is an approver, `alice` an operator
# (she made the held call), `bob` read-only. They are the same tokens the gateway authenticates
# callers with, which is the point — the desk does not invent a second notion of who you are.
ALICE = "dev-token-alice-REPLACE-ME"  # noqa: S105 — a public demo placeholder
PRIYA = "dev-token-priya-REPLACE-ME"  # noqa: S105 — a public demo placeholder
BOB = "dev-token-bob-REPLACE-ME"  # noqa: S105 — a public demo placeholder
DESK_TOKEN = "shared-desk-token"  # noqa: S105 — the read-the-page credential, not an identity


@pytest.fixture
def public_desk(desk: tuple[TestClient, str]) -> TestClient:
    """The same desk, bound where colleagues (and everyone else) can reach it.

    Two writes are waiting: ``r2000001`` requested by alice (an operator) and ``r2000002``
    requested by priya herself — the case four-eyes exists for.
    """
    _, db = desk
    queue = SqlApprovalQueue(Session(create_ledger_engine(db)))
    queue.create(
        ApprovalRequest(
            id="r2000002",
            call_id="call-4",
            ts="2026-09-08T12:02:00+00:00",
            principal="priya",
            role="approver",
            upstream="jira",
            tool="createJiraIssue",
            arguments_preview='{"summary": "raised by the approver herself"}',
        )
    )
    queue.close()

    def open_store() -> SqlLedgerStore:
        return SqlLedgerStore(Session(create_ledger_engine(db)), KEY)

    return TestClient(create_ui_app(open_store, token=DESK_TOKEN, require_verified=True))


def _decide(
    client: TestClient, credential: str, request_id: str = "r2000001", **body: object
) -> object:
    return client.post(
        f"/ui/api/pending/{request_id}/decision",
        json={"status": "approved", **body},
        headers={"Authorization": f"Bearer {credential}"},
    )


def test_a_typed_name_cannot_release_a_write_over_the_network(public_desk: TestClient) -> None:
    """The desk token proves you may LOOK. It says nothing about who you are."""
    response = _decide(public_desk, DESK_TOKEN, by="priya")
    assert response.status_code == 403
    assert "typed name proves nothing" in response.json()["detail"]
    assert public_desk.get(
        "/ui/api/pending", headers={"Authorization": f"Bearer {DESK_TOKEN}"}
    ).json(), "the write stays held for someone who may decide it"


def test_a_signed_in_approver_releases_the_write_and_is_named(public_desk: TestClient) -> None:
    response = _decide(public_desk, PRIYA, note="checked with the customer")
    assert response.status_code == 200
    decided = response.json()
    # The name comes from the credential, not from the browser — and the record says how.
    assert decided["decided_by"] == "priya"
    assert decided["decided_method"] == "token"


def test_an_operator_cannot_release_their_own_write(public_desk: TestClient) -> None:
    """alice made the held call. She is refused for the first reason that applies: an operator is
    not an approver here — and even if she were, four-eyes would stop her (below)."""
    response = _decide(public_desk, ALICE)
    assert response.status_code == 403
    assert "may not decide held writes" in response.json()["detail"]


def test_an_approver_cannot_release_their_own_write(public_desk: TestClient) -> None:
    """Four-eyes: priya may approve, but not the call she made herself."""
    response = _decide(public_desk, PRIYA, request_id="r2000002")
    assert response.status_code == 403
    assert "cannot also approve it" in response.json()["detail"]


def test_a_reader_cannot_release_a_write(public_desk: TestClient) -> None:
    response = _decide(public_desk, BOB)
    assert response.status_code == 403
    assert "may not decide held writes" in response.json()["detail"]


def test_a_body_name_cannot_override_the_credential(public_desk: TestClient) -> None:
    """Signed in as priya, claiming to be root: the credential wins."""
    assert _decide(public_desk, PRIYA, by="root").json()["decided_by"] == "priya"


def test_whoami_tells_the_page_what_it_may_offer(public_desk: TestClient) -> None:
    signed_in = public_desk.get(
        "/ui/api/whoami", headers={"Authorization": f"Bearer {PRIYA}"}
    ).json()
    assert signed_in == {
        "signed_in": True,
        "id": "priya",
        "role": "approver",
        "method": "token",
        "may_decide": True,
    }
    looking = public_desk.get(
        "/ui/api/whoami", headers={"Authorization": f"Bearer {DESK_TOKEN}"}
    ).json()
    assert looking["signed_in"] is False and looking["may_decide"] is False


def test_an_unknown_credential_opens_nothing(public_desk: TestClient) -> None:
    assert (
        public_desk.get(
            "/ui/api/summary", headers={"Authorization": "Bearer not-a-real-token"}
        ).status_code
        == 401
    )
    assert public_desk.get("/ui/api/summary").status_code == 401
