"""CLI tests for ``gatekeeper tail`` — and the ``--with-id`` column.

Reuses the same temp-backed real ``SqliteLedgerStore`` pattern as ``test_cli_show``: the call_id is
hidden by default (too wide for the table) and surfaced only with ``--with-id`` so an operator can
copy it into ``show <call_id>``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.cli import app as cli_app
from gatekeeper.db.base import Base
from gatekeeper.schemas.enums import ActionKind, Verdict
from gatekeeper.schemas.ledger import LedgerEntry

runner = CliRunner()
KEY = "k" * 64  # fake HMAC key — fixture only, never a real secret
GOOD_HMAC = "a" * 64


def _entry(call_id: str, **over: Any) -> LedgerEntry:
    base: dict[str, Any] = dict(
        call_id=call_id,
        ts="2026-06-07T17:00:00+00:00",
        principal="alice",
        role="operator",
        upstream="demo",
        tool="read_file",
        action_kind=ActionKind.READ,
        verdict=Verdict.ALLOW,
        reason="operator may read",
        payload_hash="a" * 64,
        result_summary="ok",
    )
    base.update(over)
    return LedgerEntry(**base)


@pytest.fixture
def seeded_db(tmp_path: Any, monkeypatch: Any) -> Iterator[str]:
    db_path = str(tmp_path / "audit.db")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    seed = SqliteLedgerStore(Session(engine), KEY)
    seed.append(_entry("call-one"))
    seed.append(_entry("call-two", tool="write_file", action_kind=ActionKind.WRITE))
    seed.close()

    def _fake_open(*_a: Any, **_k: Any) -> SqliteLedgerStore:
        return SqliteLedgerStore(Session(sa.create_engine(f"sqlite:///{db_path}")), KEY)

    monkeypatch.setenv("GATEKEEPER_HMAC_KEY", GOOD_HMAC)
    monkeypatch.setattr(cli_app, "open_ledger", _fake_open)
    yield db_path


def test_tail_hides_call_id_by_default(seeded_db: str):
    result = runner.invoke(cli_app.app, ["tail"])
    assert result.exit_code == 0, result.output
    assert "call-one" not in result.output  # the UUID column is opt-in
    assert "call_id" not in result.output


def test_tail_with_id_surfaces_call_id(seeded_db: str):
    result = runner.invoke(cli_app.app, ["tail", "--with-id"])
    assert result.exit_code == 0, result.output
    assert "call_id" in result.output  # header present
    assert "call-one" in result.output  # the natural key copyable into `show`
    assert "call-two" in result.output


def test_tail_with_id_is_legacy_windows_console_safe(seeded_db: str):
    result = runner.invoke(cli_app.app, ["tail", "--with-id"])
    assert result.exit_code == 0
    result.output.encode("cp1252")  # box.ASCII -> no glyphs that crash a cp1252 console
