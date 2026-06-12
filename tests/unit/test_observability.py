"""Unit — M3.4 observability: metrics registry, deny-spike detector, webhook alerter, stats CLI.

The pipeline-side recording is asserted here through real ``GatewayPipeline.handle`` calls with
fakes (same style as test_pipeline); the live /metrics route is asserted in the HTTP integration
test. The alerter never touches the network in tests (httpx.post is monkeypatched).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from gatekeeper.adapters.identity.static_token import StaticTokenResolver
from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.cli import app as cli_app
from gatekeeper.db.base import Base
from gatekeeper.domain.classify import ActionClassifier
from gatekeeper.domain.errors import IdentityError, PolicyDenied
from gatekeeper.gateway.pipeline import GatewayPipeline
from gatekeeper.infra import alerts as alerts_mod
from gatekeeper.infra.alerts import DenySpikeDetector, WebhookAlerter
from gatekeeper.infra.metrics import GatewayMetrics
from gatekeeper.schemas.enums import ActionKind, Verdict
from gatekeeper.schemas.ledger import LedgerEntry
from gatekeeper.schemas.models import Decision, Principal, ToolResult

runner = CliRunner()
KEY = "k" * 64


# --- GatewayMetrics ----------------------------------------------------------------------------
def test_metrics_p95_nearest_rank_and_render() -> None:
    m = GatewayMetrics()
    for i in range(100):  # 1..100 ms
        m.record_call("allow", (i + 1) / 1000.0)
    m.record_call("deny", 0.002)
    m.record_identity_deny()
    m.record_forward_error()

    p95 = m.overhead_p95_ms()
    assert p95 is not None and 94.0 <= p95 <= 97.0  # nearest-rank on 1..100ms + one 2ms deny

    text = m.prometheus_text(budget_ms=10.0)
    assert 'gatekeeper_calls_total{verdict="allow"} 100' in text
    assert 'gatekeeper_calls_total{verdict="deny"} 1' in text
    assert "gatekeeper_identity_denies_total 1" in text
    assert "gatekeeper_forward_errors_total 1" in text
    assert "gatekeeper_overhead_budget_ms 10.0" in text
    assert "gatekeeper_overhead_p95_ms" in text
    assert "gatekeeper_deny_rate 0.0099" in text  # 1/101


def test_metrics_empty_renders_without_p95() -> None:
    text = GatewayMetrics().prometheus_text(budget_ms=10.0)
    assert "gatekeeper_overhead_p95_ms " not in text  # no samples -> no fake number
    assert "gatekeeper_overhead_budget_ms 10.0" in text


# --- DenySpikeDetector ---------------------------------------------------------------------
def test_deny_spike_fires_once_per_episode_and_rearms() -> None:
    d = DenySpikeDetector(window_s=60, threshold=3)
    assert [d.record_deny(now=t) for t in (0.0, 1.0)] == [False, False]
    assert d.record_deny(now=2.0) is True  # threshold crossed -> fire exactly once
    assert d.record_deny(now=3.0) is False  # sustained breach -> silent (no alert storm)
    # Window drains (old denies age out) -> detector re-arms -> a NEW episode fires again.
    assert d.record_deny(now=200.0) is False
    assert d.record_deny(now=201.0) is False
    assert d.record_deny(now=202.0) is True


def test_deny_spike_rejects_nonsense_config() -> None:
    with pytest.raises(ValueError):
        DenySpikeDetector(window_s=0, threshold=5)


# --- WebhookAlerter ------------------------------------------------------------------------
class _Resp:
    status_code = 200

    def raise_for_status(self) -> None:
        return None


def test_alerter_disabled_without_url(monkeypatch: Any) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(alerts_mod.httpx, "post", lambda *a, **k: calls.append(a) or _Resp())
    assert WebhookAlerter("").fire("verify_failure", {}) is False
    assert calls == []  # never even attempts the network


def test_alerter_posts_payload_and_survives_failure(monkeypatch: Any) -> None:
    seen: dict[str, Any] = {}

    def fake_post(url: str, *, json: dict[str, Any], timeout: float) -> _Resp:
        seen.update(url=url, payload=json)
        return _Resp()

    monkeypatch.setattr(alerts_mod.httpx, "post", fake_post)
    ok = WebhookAlerter("https://hooks.test/T123").fire("deny_spike", {"denies_in_window": 12})
    assert ok is True
    assert seen["payload"]["kind"] == "deny_spike"
    assert seen["payload"]["detail"]["denies_in_window"] == 12

    def broken_post(*a: Any, **k: Any) -> _Resp:
        raise ConnectionError("receiver down")

    monkeypatch.setattr(alerts_mod.httpx, "post", broken_post)
    # Fail-SAFE: a down receiver is a False return + a log line, never an exception.
    assert WebhookAlerter("https://hooks.test/T123").fire("verify_failure", {}) is False


# --- Pipeline records metrics + fires the spike alert (real handle(), fakes for ports) -------
class _FakeLedger:
    def append(self, entry: LedgerEntry) -> LedgerEntry:
        return entry


class _FakeUpstream:
    async def forward(self, call: Any) -> ToolResult:
        return ToolResult(call_id=call.call_id, ok=True, summary="ok")


class _AllowAllPolicy:
    def evaluate(self, principal: Any, call: Any) -> Decision:
        return Decision(call_id=call.call_id, verdict=Verdict.ALLOW, reason="test allow")


class _DenyAllPolicy:
    def evaluate(self, principal: Any, call: Any) -> Decision:
        return Decision(call_id=call.call_id, verdict=Verdict.DENY, reason="test deny")


class _RecordingAlerter(WebhookAlerter):
    def __init__(self) -> None:
        super().__init__("https://hooks.test/record")  # enabled=True; fire() overridden below
        self.fired: list[tuple[str, dict[str, Any]]] = []

    def fire(self, kind: str, detail: dict[str, Any]) -> bool:
        self.fired.append((kind, detail))
        return True


async def _settled(alerter: _RecordingAlerter, timeout_s: float = 5.0) -> None:
    """Wait for the fire-and-forget worker-thread delivery (bounded; no race on slow CI)."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    # Polling is correct here: the alerter delivers from a plain worker thread (no Event to
    # await by design — alerting is fire-and-forget off the hot path); the deadline bounds it.
    while not alerter.fired and asyncio.get_running_loop().time() < deadline:  # noqa: ASYNC110
        await asyncio.sleep(0.01)


def _pipeline(policy: Any, metrics: GatewayMetrics, alerter: _RecordingAlerter) -> GatewayPipeline:
    return GatewayPipeline(
        identity=StaticTokenResolver(
            {"tok": Principal(id="alice", role="operator", tenant="default")}
        ),
        classifier=ActionClassifier(name_patterns=[], upstream_annotations={}),
        policy=policy,
        ledger=_FakeLedger(),
        upstream=_FakeUpstream(),
        hmac_key=KEY,
        metrics=metrics,
        deny_detector=DenySpikeDetector(window_s=60, threshold=2),
        alerter=alerter,
    )


async def test_pipeline_records_allow_metrics_with_overhead() -> None:
    metrics, alerter = GatewayMetrics(), _RecordingAlerter()
    pipe = _pipeline(_AllowAllPolicy(), metrics, alerter)
    result = await pipe.handle(token="tok", upstream="u", tool="t", arguments={}, call_id="c1")
    assert result.ok
    assert metrics.calls_by_verdict == {"allow": 1}
    assert metrics.overhead_p95_ms() is not None  # governance segments were timed
    assert alerter.fired == []


async def test_pipeline_denies_feed_spike_detector_and_alert_once() -> None:
    metrics, alerter = GatewayMetrics(), _RecordingAlerter()
    pipe = _pipeline(_DenyAllPolicy(), metrics, alerter)
    for i in range(3):
        with pytest.raises(PolicyDenied):
            await pipe.handle(token="tok", upstream="u", tool="t", arguments={}, call_id=f"c{i}")
    assert metrics.calls_by_verdict == {"deny": 3}
    # Threshold 2 -> exactly ONE alert for the episode, with operator-useful detail.
    # (Delivery is fire-and-forget on a worker thread by design — wait for it briefly.)
    await _settled(alerter)
    assert [k for k, _ in alerter.fired] == ["deny_spike"]
    assert alerter.fired[0][1]["last_target"] == "u:t"


async def test_pipeline_identity_deny_counts_and_feeds_spike() -> None:
    metrics, alerter = GatewayMetrics(), _RecordingAlerter()
    pipe = _pipeline(_AllowAllPolicy(), metrics, alerter)
    for i in range(2):
        with pytest.raises(IdentityError):
            await pipe.handle(token="forged", upstream="u", tool="t", arguments={}, call_id=f"i{i}")
    assert metrics.identity_denies == 2
    assert metrics.calls_by_verdict == {"deny": 2}
    await _settled(alerter)
    assert [k for k, _ in alerter.fired] == ["deny_spike"]


# --- stats CLI (ledger-derived; counts each call once via its decision entry) -----------------
def _entry(call_id: str, **over: Any) -> LedgerEntry:
    base: dict[str, Any] = dict(
        call_id=call_id,
        ts="2026-06-12T10:00:00+00:00",
        principal="alice",
        role="operator",
        upstream="demo",
        tool="read_file",
        action_kind=ActionKind.READ,
        verdict=Verdict.ALLOW,
        reason="ok",
        payload_hash="a" * 64,
        result_summary="",
    )
    base.update(over)
    return LedgerEntry(**base)


@pytest.fixture
def seeded_db(tmp_path: Any, monkeypatch: Any) -> Iterator[str]:
    db_path = str(tmp_path / "audit.db")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    seed = SqliteLedgerStore(Session(engine), KEY)
    # Two allowed calls (decision + outcome pairs -> must be counted ONCE each) + one deny.
    for cid in ("a1", "a2"):
        seed.append(_entry(cid))
        seed.append(_entry(cid, result_summary="ok"))
    seed.append(
        _entry(
            "d1",
            principal="bob",
            role="readonly",
            tool="write_file",
            action_kind=ActionKind.WRITE,
            verdict=Verdict.DENY,
            reason="denied",
        )
    )
    seed.close()

    def _fake_open(*_a: Any, **_k: Any) -> SqliteLedgerStore:
        return SqliteLedgerStore(Session(sa.create_engine(f"sqlite:///{db_path}")), KEY)

    monkeypatch.setenv("GATEKEEPER_HMAC_KEY", "a" * 64)
    monkeypatch.setattr(cli_app, "open_ledger", _fake_open)
    yield db_path


def test_stats_counts_calls_once_and_shows_rates(seeded_db: str) -> None:
    result = runner.invoke(cli_app.app, ["stats"])
    assert result.exit_code == 0, result.output
    assert "last 3 calls" in result.output  # 3 calls, not 5 entries
    assert "2 (67%)" in result.output  # allowed
    assert "1 (33%)" in result.output  # denied
    assert "bob=1" in result.output  # denies by principal
    assert "demo:read_file=2" in result.output  # busiest tools
    result.output.encode("cp1252")  # legacy-console safe


def test_stats_empty_ledger(tmp_path: Any, monkeypatch: Any) -> None:
    db_path = str(tmp_path / "empty.db")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    def _fake_open(*_a: Any, **_k: Any) -> SqliteLedgerStore:
        return SqliteLedgerStore(Session(sa.create_engine(f"sqlite:///{db_path}")), KEY)

    monkeypatch.setattr(cli_app, "open_ledger", _fake_open)
    result = runner.invoke(cli_app.app, ["stats"])
    assert result.exit_code == 0
    assert "ledger is empty" in result.output
