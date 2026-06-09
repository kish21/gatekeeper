"""CLI tests for ``gatekeeper show <call_id>`` — inspect one recorded decision.

``open_ledger`` is monkeypatched to a temp-backed real ``SqliteLedgerStore`` so we exercise the
actual command + the real ``get()`` path without touching the dev ledger. Asserts exit codes and
that no token/HMAC key ever leaks into the rendered output.
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
SECRET_TOKEN = "dev-token-alice-SECRET"  # must NEVER appear in `show` output


def _entry(call_id: str, **over: Any) -> LedgerEntry:
    base: dict[str, Any] = dict(
        call_id=call_id,
        ts="2026-06-07T17:00:00+00:00",
        principal="alice",
        role="operator",
        upstream="demo",
        tool="write_file",
        action_kind=ActionKind.WRITE,
        verdict=Verdict.ALLOW,
        reason="operator may write",
        payload_hash="a" * 64,
        result_summary="ok: 12 bytes written",
    )
    base.update(over)
    return LedgerEntry(**base)


@pytest.fixture
def seeded_db(tmp_path: Any, monkeypatch: Any) -> Iterator[str]:
    """A temp ledger DB seeded with one ALLOW and one DENY entry; CLI points at it."""
    db_path = str(tmp_path / "audit.db")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    seed = SqliteLedgerStore(Session(engine), KEY)
    seed.append(_entry("call-allow"))
    seed.append(
        _entry(
            "call-deny",
            principal="bob",
            role="readonly",
            verdict=Verdict.DENY,
            reason="readonly may not write",
            result_summary="",
        )
    )
    seed.close()

    # Each command opens its own store (the real ctx manager closes it) -> hand back a fresh one.
    def _fake_open(*_a: Any, **_k: Any) -> SqliteLedgerStore:
        return SqliteLedgerStore(Session(sa.create_engine(f"sqlite:///{db_path}")), KEY)

    monkeypatch.setenv("GATEKEEPER_HMAC_KEY", GOOD_HMAC)
    monkeypatch.setattr(cli_app, "open_ledger", _fake_open)
    yield db_path


def test_show_found_allow(seeded_db: str):
    result = runner.invoke(cli_app.app, ["show", "call-allow"])
    assert result.exit_code == 0, result.output
    assert "call-allow" in result.output
    assert "allow" in result.output
    assert "operator may write" in result.output
    assert "demo:write_file" in result.output


def test_show_found_deny(seeded_db: str):
    result = runner.invoke(cli_app.app, ["show", "call-deny"])
    assert result.exit_code == 0, result.output
    assert "deny" in result.output
    assert "readonly may not write" in result.output


def test_show_not_found_exits_1(seeded_db: str):
    result = runner.invoke(cli_app.app, ["show", "no-such-call"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_show_never_leaks_token_or_key(seeded_db: str):
    result = runner.invoke(cli_app.app, ["show", "call-allow"])
    assert result.exit_code == 0
    # The audit record holds principal/role + HMAC digests, never the bearer token or HMAC key.
    assert SECRET_TOKEN not in result.output
    assert KEY not in result.output
    assert GOOD_HMAC not in result.output


def test_show_output_is_legacy_windows_console_safe(seeded_db: str):
    result = runner.invoke(cli_app.app, ["show", "call-allow"])
    assert result.exit_code == 0
    result.output.encode("cp1252")  # box.ASCII -> no glyphs that crash a cp1252 console
