"""Latency eval harness — the /eval measurement behind the ADR-001 perf budget.

Measures the **added gateway overhead** of the M1 governance pipeline over a *direct* upstream
call — i.e. the deterministic per-call work GateKeeperAI inserts:

    classify (read/write)  ->  Cedar RBAC eval  ->  keyed-HMAC + SQLite append (audit-before-act)
    [ ALLOW only: + forward + a 2nd chained append (outcome) ]

Upstream I/O is **excluded by design**: the upstream is a zero-latency fake, so what's timed is
exactly the overhead the architecture budgets (Architecture#Perf budget / ADR-001: p95 < ~10 ms).
Every collaborator is the **real** one (real Cedar engine on the shipped ``policies/``, real
``ActionClassifier`` from config, real keyed-HMAC hash-chain, real file-backed SQLite ledger)
so the number is representative, not a toy.

Reproducible + config-gated (eval-integrity): the p95 budget is read from
``config/platform.yaml`` (``perf.overhead_p95_ms``) — NOT hardcoded — and a p95 above it exits
non-zero (a regression fails). This is the recorded baseline M2 will be measured against.

Run::

    python -m tests.eval.bench_governance_latency            # scenario latency (default)
    python -m tests.eval.bench_governance_latency -n 5000    # more samples
    python -m tests.eval.bench_governance_latency --diagnose # component breakdown + WAL mitigation

``--diagnose`` reproduces the overhead attribution (Cedar vs HMAC vs SQLite commit) and the
WAL journal-mode lever cited in PRODUCT.md#Evaluation, so those numbers are reproducible here, not
asserted in prose.

Operational failures (a call that errors) are reported **separately** from the latency numbers, so
an errored run can never masquerade as a fast/slow quality result.

**Honest caveat (biases the number *optimistic*):** the harness sets the ``gatekeeper`` logger to
ERROR and injects a no-op reporter, so prod's per-call INFO log + observability hook (sub-ms each)
are excluded. The real overhead is therefore marginally *higher* than reported — which only
strengthens the over-budget finding, never weakens it.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import secrets
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from gatekeeper.adapters.identity.static_token import StaticTokenResolver
from gatekeeper.adapters.ledger.hashchain import compute_entry_hash, compute_payload_hash
from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.adapters.policy.cedar import CedarPolicyEngine
from gatekeeper.config.loader import load_config
from gatekeeper.db import models as _models  # noqa: F401 — registers ledger_entry on Base.metadata
from gatekeeper.db.base import Base
from gatekeeper.domain.classify import ActionClassifier
from gatekeeper.domain.errors import PolicyDenied
from gatekeeper.gateway.factory import _build_classifier  # config-driven classifier builder
from gatekeeper.gateway.pipeline import GatewayPipeline
from gatekeeper.schemas.enums import ActionKind, Verdict
from gatekeeper.schemas.ledger import GENESIS_HASH, LedgerEntry
from gatekeeper.schemas.models import Principal, ToolCall, ToolResult

_DEFAULT_ITERS = 2000
_WARMUP = 100  # discard warmup samples (JIT-less, but caches/connection settle)


class _SilentReporter:
    """No-op ``ErrorReporter`` — keeps the timing report clean (deny events are expected here)."""

    def report(self, event: str, /, **fields: object) -> None:
        return None


class _ZeroLatencyUpstream:
    """A faithful ``UpstreamClient`` that returns instantly — isolates *gateway* overhead.

    The real ``forward`` does network/subprocess I/O whose latency is the upstream's, not the
    gateway's. Replacing only this leaves every governance step real while removing the variable
    the budget explicitly excludes.
    """

    async def forward(self, call: ToolCall) -> ToolResult:
        return ToolResult(call_id=call.call_id, ok=True, summary="bench: ok")

    async def aclose(self) -> None:  # pragma: no cover - parity with the real client
        return None


@dataclass(frozen=True)
class _Scenario:
    """One representative call shape on the live path (token chosen to hit allow/deny)."""

    label: str
    token: str
    upstream: str
    tool: str
    expect_denied: bool
    appends: int  # ledger appends this path performs (allow=2, deny=1) — for context


def _percentile(samples: list[float], pct: float) -> float:
    """Textbook nearest-rank percentile (1-based rank = ceil(p/100 * N)) over samples (ms)."""
    if not samples:
        return float("nan")
    ordered = sorted(samples)
    k = max(0, min(len(ordered) - 1, math.ceil(pct / 100.0 * len(ordered)) - 1))
    return ordered[k]


def _time_calls(fn: Callable[[int], object], n: int, warmup: int) -> tuple[float, float]:
    """Time ``fn(i)`` n+warmup times; return (p50, p95) ms over the post-warmup samples."""
    times: list[float] = []
    for i in range(n + warmup):
        t0 = time.perf_counter()
        fn(i)
        if i >= warmup:
            times.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(times), _percentile(times, 95)


def _token_for_role(identities: list[dict[str, Any]], role: str) -> str:
    for raw in identities:
        if str(raw.get("role")) == role:
            return str(raw["token"])
    raise SystemExit(f"no identity with role {role!r} in config/identities.yaml")


async def _run(iters: int) -> int:
    # Quiet the per-call governance logs/reporter — this is a timing harness, not a deny audit;
    # the JSON deny lines are real but would drown the percentile report.
    import logging

    logging.getLogger("gatekeeper").setLevel(logging.ERROR)

    config = load_config()
    platform, product = config["platform"], config["product"]
    identities, upstreams = config["identities"], config["upstreams"]

    budget_ms = float(platform.get("perf", {}).get("overhead_p95_ms", 10.0))
    policy_dir = platform.get("policy", {}).get("dir", "./policies")

    # --- real collaborators (only the upstream is faked) -----------------------------------
    identity = StaticTokenResolver.from_config(identities)
    classifier: ActionClassifier = _build_classifier(product, upstreams)
    policy = CedarPolicyEngine.from_config(policy_dir)

    tmp = Path(tempfile.mkdtemp(prefix="gk-bench-")) / "bench.db"
    engine = create_engine(f"sqlite:///{tmp}")
    Base.metadata.create_all(engine)  # the REAL ledger_entry schema (same table as the migration)
    ledger = SqliteLedgerStore(Session(engine), key=secrets.token_hex(32))

    pipeline = GatewayPipeline(
        identity=identity,
        classifier=classifier,
        policy=policy,
        ledger=ledger,
        upstream=_ZeroLatencyUpstream(),
        hmac_key=secrets.token_hex(32),
        reporter=_SilentReporter(),
    )

    # Representative call shapes on the real policy: allowed read, allowed write, denied write.
    scenarios = [
        _Scenario(
            "allow-read ",
            _token_for_role(identities, "readonly"),
            "demo-files",
            "read_file",
            False,
            2,
        ),
        _Scenario(
            "allow-write",
            _token_for_role(identities, "operator"),
            "demo-files",
            "write_file",
            False,
            2,
        ),
        _Scenario(
            "deny-write ",
            _token_for_role(identities, "readonly"),
            "demo-files",
            "write_file",
            True,
            1,
        ),
    ]

    per_scenario: dict[str, list[float]] = {s.label: [] for s in scenarios}
    overall: list[float] = []
    op_failures = 0  # operational failures (unexpected errors) — counted SEPARATELY from latency

    total = (iters + _WARMUP) * len(scenarios)
    seq = 0
    for i in range(iters + _WARMUP):
        for s in scenarios:
            seq += 1
            t0 = time.perf_counter()
            try:
                await pipeline.handle(
                    token=s.token,
                    upstream=s.upstream,
                    tool=s.tool,
                    arguments={"path": "bench.txt", "i": i},
                    call_id=f"bench-{s.label.strip()}-{seq}",
                )
                got_denied = False
            except PolicyDenied:
                got_denied = True  # an EXPECTED deny is a correct outcome, not an op failure
            except Exception as exc:  # noqa: BLE001 — any other error is operational
                op_failures += 1
                print(f"  ! operational failure on {s.label}: {type(exc).__name__}: {exc}")
                continue
            dt_ms = (time.perf_counter() - t0) * 1000.0
            if got_denied != s.expect_denied:
                op_failures += 1  # wrong verdict = correctness failure, not a latency sample
                continue
            if i >= _WARMUP:  # discard warmup
                per_scenario[s.label].append(dt_ms)
                overall.append(dt_ms)

    ledger.close()

    # --- report ----------------------------------------------------------------------------
    print()
    print("GateKeeperAI - M1 governance overhead (added latency over a direct call)")
    print(f"  samples/scenario = {iters} (after {_WARMUP} warmup) | upstream = zero-latency fake")
    print(f"  real: Cedar({policy_dir}) | ActionClassifier(config) | keyed-HMAC | file SQLite")
    print(f"  {'scenario':<12} {'appends':>7} {'p50':>8} {'p95':>8} {'p99':>8} {'max':>8}  (ms)")
    for s in scenarios:
        xs = per_scenario[s.label]
        if not xs:
            print(f"  {s.label:<12} {s.appends:>7}   (no samples)")
            continue
        print(
            f"  {s.label:<12} {s.appends:>7} "
            f"{statistics.median(xs):>8.3f} {_percentile(xs, 95):>8.3f} "
            f"{_percentile(xs, 99):>8.3f} {max(xs):>8.3f}"
        )

    p95 = _percentile(overall, 95)
    p99 = _percentile(overall, 99)
    print(
        f"  {'OVERALL':<12} {'':>7} "
        f"{statistics.median(overall):>8.3f} {p95:>8.3f} {p99:>8.3f} {max(overall):>8.3f}"
    )
    print()
    print(f"  operational failures (separated from quality): {op_failures} / {total}")
    print(f"  budget (config platform.yaml perf.overhead_p95_ms): p95 < {budget_ms:.1f} ms")

    if op_failures:
        print(
            "  RESULT: FAIL - operational failures occurred; latency numbers are not trustworthy."
        )
        return 2
    if p95 > budget_ms:
        print(f"  RESULT: FAIL - p95 {p95:.3f} ms exceeds budget {budget_ms:.1f} ms (regression).")
        return 1
    print(f"  RESULT: PASS - p95 {p95:.3f} ms within the {budget_ms:.1f} ms budget.")
    return 0


def _sample_entry() -> LedgerEntry:
    """A representative ledger entry for isolated-append timing (same shape the pipeline writes)."""
    return LedgerEntry(
        call_id="diag",
        ts="2026-01-01T00:00:00+00:00",
        tenant="default",
        principal="bob",
        role="readonly",
        upstream="demo-files",
        tool="read_file",
        action_kind=ActionKind.READ,
        verdict=Verdict.ALLOW,
        reason="ok",
        payload_hash="0" * 64,
        result_summary="",
    )


def _make_store(journal: str | None, sync: str | None, key: str) -> SqliteLedgerStore:
    """A real file-backed ledger store, optionally with explicit journal/synchronous PRAGMAs."""
    tmp = Path(tempfile.mkdtemp(prefix="gk-diag-")) / "diag.db"
    engine = create_engine(f"sqlite:///{tmp}")
    if journal or sync:

        @event.listens_for(engine, "connect")
        def _set_pragmas(dbapi: Any, _record: Any) -> None:  # noqa: ANN401
            cur = dbapi.cursor()
            if journal:
                cur.execute(f"PRAGMA journal_mode={journal}")
            if sync:
                cur.execute(f"PRAGMA synchronous={sync}")
            cur.close()

    Base.metadata.create_all(engine)
    return SqliteLedgerStore(Session(engine), key=key)


def _diagnose(iters: int) -> int:
    """Reproduce the /eval component breakdown + WAL-mitigation tables from the committed code.

    Attributes the overhead to its parts (Cedar vs HMAC vs SQLite commit) and measures the WAL
    journal-mode lever — the numbers cited in PRODUCT.md#Evaluation, made reproducible here.
    """
    config = load_config()
    policy_dir = config["platform"].get("policy", {}).get("dir", "./policies")
    key = secrets.token_hex(32)

    policy = CedarPolicyEngine.from_config(policy_dir)
    principal = Principal(id="bob", role="readonly")

    def cedar(i: int) -> object:
        call = ToolCall(
            call_id=f"c{i}",
            upstream="demo-files",
            tool="read_file",
            arguments={},
            action_kind=ActionKind.READ,
        )
        return policy.evaluate(principal, call)

    entry = _sample_entry()

    def hmac_x2(i: int) -> object:
        compute_payload_hash(key, {"path": "x", "i": i})
        return compute_entry_hash(key, GENESIS_HASH, entry)

    current = _make_store(None, None, key)  # SQLAlchemy default == prod (synchronous=FULL, DELETE)
    wal_normal = _make_store("WAL", "NORMAL", key)
    wal_full = _make_store("WAL", "FULL", key)

    print()
    print("GateKeeperAI - M1 overhead attribution + WAL-mitigation (component diagnose)")
    print(f"  samples = {iters} (after {_WARMUP} warmup) | real Cedar/HMAC/SQLite, no upstream")
    print(f"  {'component':<34} {'p50':>8} {'p95':>8}  (ms)")
    for label, fn in (
        ("Cedar RBAC eval", cedar),
        ("keyed-HMAC x2 (payload + entry)", hmac_x2),
        ("SQLite append - current (FULL/DELETE)", lambda i: current.append(_sample_entry())),
        ("SQLite append - WAL + synchronous=NORMAL", lambda i: wal_normal.append(_sample_entry())),
        ("SQLite append - WAL + synchronous=FULL", lambda i: wal_full.append(_sample_entry())),
    ):
        p50, p95 = _time_calls(fn, iters, _WARMUP)
        print(f"  {label:<34} {p50:>8.3f} {p95:>8.3f}")
    for store in (current, wal_normal, wal_full):
        store.close()
    print()
    print("  note: a governed ALLOW commits TWICE (decision + outcome), so the per-call overhead")
    print("        is ~2x the single-append number above. WAL is a config-only engine PRAGMA.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--iters", type=int, default=_DEFAULT_ITERS, help="samples/scenario")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="component breakdown (Cedar/HMAC/SQLite) + WAL-mitigation table instead of scenarios",
    )
    args = parser.parse_args()
    if args.diagnose:
        return _diagnose(args.iters)
    return asyncio.run(_run(args.iters))


if __name__ == "__main__":
    sys.exit(main())
