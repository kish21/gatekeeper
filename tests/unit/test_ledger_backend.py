"""Unit — choosing the ledger backend, and the two behaviours that differ between them.

The gateway runs its ledger on a SQLite file or on Postgres, decided by config alone. Three things
have to be true for that to be safe, and none of them needs a database to check:
  * a copy-pasted managed-database URL reaches SQLAlchemy with the driver we actually ship;
  * a URL never reaches a log, an error, or ``doctor`` with its password in it;
  * the append path serializes writers on Postgres (advisory lock) and does not on SQLite (whose
    engine already opens every write transaction with BEGIN IMMEDIATE).
"""

from __future__ import annotations

from typing import Any

import pytest

from gatekeeper.config.loader import Settings, ledger_target, load_config
from gatekeeper.db.base import (
    CHAIN_LOCK_ID,
    backend_name,
    database_url,
    is_url,
    lock_chain,
    redact_url,
)


class _FakeBind:
    def __init__(self, name: str) -> None:
        self.dialect = type("_D", (), {"name": name})()


class _FakeSession:
    """Records what the store would send to the database, without a database."""

    def __init__(self, dialect: str) -> None:
        self._bind = _FakeBind(dialect)
        self.statements: list[tuple[str, dict[str, Any]]] = []

    def get_bind(self) -> _FakeBind:
        return self._bind

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> None:
        self.statements.append((str(statement), params or {}))


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("/data/audit.db", "sqlite:////data/audit.db"),
        ("./audit.db", "sqlite:///./audit.db"),
        # Azure and most managed providers hand out a bare postgresql:// URL; without pinning the
        # driver SQLAlchemy would look for psycopg2, which the image does not ship.
        ("postgresql://u:p@host:5432/gk", "postgresql+psycopg://u:p@host:5432/gk"),
        ("postgres://u:p@host/gk", "postgresql+psycopg://u:p@host/gk"),
        ("postgresql+psycopg://u:p@host/gk", "postgresql+psycopg://u:p@host/gk"),
    ],
)
def test_database_url_normalizes_the_target(target: str, expected: str) -> None:
    assert database_url(target) == expected


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("postgresql://gk:s3cret@db.postgres.database.azure.com/gk", "***"),
        ("postgresql://gk:s3cret@db/gk?sslmode=require", "***"),
    ],
)
def test_redact_url_hides_the_password(target: str, expected: str) -> None:
    redacted = redact_url(target)
    assert expected in redacted
    assert "s3cret" not in redacted
    assert redacted.startswith("postgresql://gk:")


def test_redact_url_leaves_a_file_path_alone() -> None:
    assert redact_url("/data/audit.db") == "/data/audit.db"
    assert is_url("/data/audit.db") is False


def test_backend_name_reports_what_is_configured() -> None:
    assert backend_name("/data/audit.db") == "sqlite"
    assert backend_name("postgresql://u:p@host/gk") == "postgres"


def test_chain_lock_is_taken_on_postgres() -> None:
    """The append path must serialize replicas before it reads the chain head."""
    session = _FakeSession("postgresql")
    lock_chain(session)
    statement, params = session.statements[0]
    assert "pg_advisory_xact_lock" in statement
    assert params == {"lock_id": CHAIN_LOCK_ID}


def test_chain_lock_is_not_taken_on_sqlite() -> None:
    """SQLite needs no advisory lock: BEGIN IMMEDIATE already holds the write lock."""
    session = _FakeSession("sqlite")
    lock_chain(session)
    assert session.statements == []


def test_ledger_url_wins_over_the_file_path(tmp_path: Any) -> None:
    """One environment variable moves the whole gateway onto the durable ledger."""
    url = "postgresql://gk:pw@db.example.com:5432/gk"
    config = load_config(Settings(ledger_path=str(tmp_path / "audit.db"), ledger_url=url))
    assert ledger_target(config) == url


def test_without_a_url_the_ledger_is_the_configured_file(tmp_path: Any) -> None:
    config = load_config(Settings(ledger_path=str(tmp_path / "audit.db")))
    assert ledger_target(config) == str(tmp_path / "audit.db")
