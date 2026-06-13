"""Transport-overhead eval harness — the M3.1 /eval re-measurement.

The M3.1 architecture addendum recorded an explicitly **aspirational** budget: HTTP transport adds
**< ~5 ms p95 over stdio on loopback** (ASGI dispatch + localhost hop), to be re-measured here
before being treated as fact (the harvested budget rule: never assert an unmeasured number).

What is measured: the **real product binary** (``python -m gatekeeper.cli.app serve``) is launched
as a subprocess twice — once per transport — with an identical temp config (same shipped Cedar
policy, same ``demo_file_server`` upstream, fresh temp ledger each) and driven by the official MCP
client. Two operations are timed per transport:

* ``tools/list``  — resolves identity + renders the tool index, **no ledger commit** → a
  low-noise isolation of pure transport + framing cost (the thing the budget is about).
* ``tools/call``  — the full governed path (classify → Cedar → 2 fsync'd appends → forward) → the
  end-to-end per-call number an agent actually experiences on each transport.

The **gated** number is the ``tools/list`` (no-ledger) **HTTP − stdio p95 delta** — that isolates
exactly what the M3.1 budget bounds ("ASGI dispatch + localhost hop"), with no fsync in the path.
It is gated against ``config/platform.yaml perf.http_transport_overhead_p95_ms`` (config, not
hardcoded); a delta above it exits non-zero. The governed ``tools/call`` delta is reported as
end-to-end context only — its p95 is dominated by the carried (M1) fsync-baseline tail jitter on a
shared box, so gating it would measure the wrong thing. Operational failures (errored calls,
``isError`` results) are counted **separately** so they can never masquerade as latency samples.

Unlike ``bench_governance_latency`` (which silences logs to isolate pipeline cost), per-call INFO
logging stays ON here — it is identical on both sides, so it cancels in the delta while keeping
each absolute number representative of a real run.

Run::

    python -m tests.eval.bench_transport_overhead             # default sample counts
    python -m tests.eval.bench_transport_overhead -n 500      # more governed-call samples
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import anyio
import yaml
from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from sqlalchemy import create_engine

from gatekeeper.db import models as _models  # noqa: F401 — registers ledger_entry on Base.metadata
from gatekeeper.db.base import Base
from tests.eval.bench_governance_latency import _percentile
from tests.integration.http_harness import free_port

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CALL_ITERS = 300
_DEFAULT_LIST_ITERS = 1000
_CALL_WARMUP = 30
_LIST_WARMUP = 100
_BOOT_TIMEOUT_S = 60.0
_DEFAULT_TRANSPORT_BUDGET_MS = 5.0  # perf.http_transport_overhead_p95_ms fallback (M3.1 addendum)


@dataclass
class _Samples:
    """Timed round-trips (ms) for one transport, op failures counted separately."""

    list_ms: list[float]
    call_ms: list[float]
    op_failures: int


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    return dict(loaded) if loaded else {}


def _operator_token(identities: Path) -> str:
    for raw in _load_yaml(identities).get("principals", []):
        if str(raw.get("role")) == "operator":
            return str(raw["token"])
    raise SystemExit("no identity with role 'operator' in config/identities.yaml")


def _make_config_dir(base: Path, label: str, http_port: int) -> tuple[Path, Path]:
    """A temp GATEKEEPER_CONFIG_DIR: real config, but a fresh temp ledger + only demo-files.

    The third-party ``time`` upstream is dropped (its availability is environment-dependent and
    irrelevant here); ``demo_file_server`` is sandboxed to a temp dir via its env knob.
    """
    cfg = base / f"config-{label}"
    cfg.mkdir(parents=True)
    sandbox = base / f"sandbox-{label}"
    sandbox.mkdir()

    platform = _load_yaml(_REPO_ROOT / "config" / "platform.yaml")
    platform.setdefault("ledger", {})["path"] = str(base / f"audit-{label}.db")
    platform.setdefault("transport", {})["http_port"] = http_port
    (cfg / "platform.yaml").write_text(yaml.safe_dump(platform), encoding="utf-8")

    upstreams = {
        "upstreams": [
            {
                "name": "demo-files",
                "transport": "stdio",
                "command": ["python", "-m", "examples.demo_file_server"],
                "env": {"DEMO_FILE_ROOT": str(sandbox)},
                "writes": ["write_file", "delete_file"],
                "reads": ["read_file", "list_dir"],
            }
        ]
    }
    (cfg / "upstreams.yaml").write_text(yaml.safe_dump(upstreams), encoding="utf-8")

    shutil.copy(_REPO_ROOT / "config" / "product.yaml", cfg / "product.yaml")
    shutil.copy(_REPO_ROOT / "config" / "identities.yaml", cfg / "identities.yaml")

    ledger_path = Path(platform["ledger"]["path"])
    engine = create_engine(f"sqlite:///{ledger_path}")
    Base.metadata.create_all(engine)  # the REAL ledger_entry schema (same table as the migration)
    engine.dispose()
    return cfg, ledger_path


def _subprocess_env(cfg_dir: Path, hmac_key: str, token: str) -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["GATEKEEPER_CONFIG_DIR"] = str(cfg_dir)
    env["GATEKEEPER_HMAC_KEY"] = hmac_key
    env["GATEKEEPER_AGENT_TOKEN"] = token  # used by stdio only; harmless for http
    return env


async def _drive(session: ClientSession, call_iters: int, list_iters: int) -> _Samples:
    """Time list/call round-trips on an initialized session; failures counted, not timed."""
    samples = _Samples(list_ms=[], call_ms=[], op_failures=0)

    for i in range(list_iters + _LIST_WARMUP):
        t0 = time.perf_counter()
        try:
            await session.list_tools()
        except Exception as exc:  # noqa: BLE001 — any error here is operational
            samples.op_failures += 1
            print(f"  ! operational failure on tools/list: {type(exc).__name__}: {exc}")
            continue
        if i >= _LIST_WARMUP:
            samples.list_ms.append((time.perf_counter() - t0) * 1000.0)

    for i in range(call_iters + _CALL_WARMUP):
        t0 = time.perf_counter()
        try:
            result = await session.call_tool("list_dir", {"path": "."})
        except Exception as exc:  # noqa: BLE001
            samples.op_failures += 1
            print(f"  ! operational failure on tools/call: {type(exc).__name__}: {exc}")
            continue
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if result.isError:  # an errored governed call is an op failure, never a latency sample
            samples.op_failures += 1
            continue
        if i >= _CALL_WARMUP:
            samples.call_ms.append(dt_ms)

    return samples


def _is_teardown_race(exc: BaseException) -> bool:
    """True if ``exc`` is (or wraps) only the SDK's stdio-teardown ``BrokenResourceError``.

    When the gateway subprocess is torn down, the MCP stdio client's background ``stdout_reader``
    task can lose its receiver and raise ``BrokenResourceError`` from the context-manager exit —
    AFTER the measurement loop has already returned its samples. It is a cleanup-race artifact
    (the same MCP-SDK stdio teardown family the codebase documents in test_upstream_lifecycle),
    never a measurement failure, so a run whose ONLY failure is this is still trustworthy.
    """
    if isinstance(exc, BaseExceptionGroup):
        return all(_is_teardown_race(sub) for sub in exc.exceptions)
    return isinstance(exc, anyio.BrokenResourceError)


async def _run_stdio(
    env: dict[str, str], errlog: TextIO, call_iters: int, list_iters: int
) -> _Samples:
    """The real binary over real stdio pipes, driven by the official MCP stdio client."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "gatekeeper.cli.app", "serve", "--transport", "stdio"],
        env=env,
        cwd=str(_REPO_ROOT),
    )
    samples: _Samples | None = None
    try:
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                async with asyncio.timeout(_BOOT_TIMEOUT_S):
                    await session.initialize()
                samples = await _drive(session, call_iters, list_iters)
    except BaseException as exc:  # noqa: BLE001 — only a pure teardown race is swallowed
        if samples is not None and _is_teardown_race(exc):
            print("  (stdio teardown race after measurement — samples already collected, ignored)")
            return samples
        raise
    return samples


def _boot_http(env: dict[str, str], errlog: TextIO, port: int) -> subprocess.Popen[bytes]:
    """Spawn the real binary over HTTP and block (sync, pre-loop) until /healthz answers 200."""
    proc = subprocess.Popen(  # noqa: S603 — our own binary, arg-vector, no shell
        [sys.executable, "-m", "gatekeeper.cli.app", "serve", "--transport", "http"],
        env=env,
        cwd=str(_REPO_ROOT),
        stdout=errlog,
        stderr=errlog,
    )
    deadline = time.monotonic() + _BOOT_TIMEOUT_S
    while True:  # poll /healthz — uvicorn exposes no out-of-process readiness signal
        if proc.poll() is not None:
            raise SystemExit(f"http gateway exited during boot (code {proc.returncode})")
        try:
            with urllib.request.urlopen(  # noqa: S310 — fixed loopback URL
                f"http://127.0.0.1:{port}/healthz", timeout=2
            ) as resp:
                if resp.status == 200:
                    return proc
        except OSError:
            pass
        if time.monotonic() > deadline:
            proc.terminate()
            raise SystemExit("http gateway did not become healthy in time")
        time.sleep(0.1)


async def _run_http(port: int, token: str, call_iters: int, list_iters: int) -> _Samples:
    """Drive an already-booted HTTP gateway with the official Streamable HTTP client."""
    headers = {"Authorization": f"Bearer {token}"}
    async with streamablehttp_client(f"http://127.0.0.1:{port}/mcp", headers=headers) as (
        read,
        write,
        _sid,
    ):
        async with ClientSession(read, write) as session:
            async with asyncio.timeout(_BOOT_TIMEOUT_S):
                await session.initialize()
            return await _drive(session, call_iters, list_iters)


def _row(label: str, transport: str, xs: list[float]) -> str:
    return (
        f"  {label:<24} {transport:<6} "
        f"{statistics.median(xs):>8.3f} {_percentile(xs, 95):>8.3f} {max(xs):>8.3f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-n", "--iters", type=int, default=_DEFAULT_CALL_ITERS, help="governed tools/call samples"
    )
    parser.add_argument(
        "-m", "--list-iters", type=int, default=_DEFAULT_LIST_ITERS, help="tools/list samples"
    )
    args = parser.parse_args()

    import secrets as _secrets

    platform = _load_yaml(_REPO_ROOT / "config" / "platform.yaml")
    budget_ms = float(
        platform.get("perf", {}).get("http_transport_overhead_p95_ms", _DEFAULT_TRANSPORT_BUDGET_MS)
    )
    token = _operator_token(_REPO_ROOT / "config" / "identities.yaml")
    hmac_key = _secrets.token_hex(32)

    base = Path(tempfile.mkdtemp(prefix="gk-transport-bench-"))
    port = free_port()
    stdio_cfg, _ = _make_config_dir(base, "stdio", port)
    http_cfg, _ = _make_config_dir(base, "http", port)

    with (base / "gateway-stdio.log").open("w", encoding="utf-8") as stdio_log:
        stdio = asyncio.run(
            _run_stdio(
                _subprocess_env(stdio_cfg, hmac_key, token), stdio_log, args.iters, args.list_iters
            )
        )
    with (base / "gateway-http.log").open("w", encoding="utf-8") as http_log:
        proc = _boot_http(_subprocess_env(http_cfg, hmac_key, token), http_log, port)
        try:
            http = asyncio.run(_run_http(port, token, args.iters, args.list_iters))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    total = 2 * (args.iters + _CALL_WARMUP + args.list_iters + _LIST_WARMUP)
    failures = stdio.op_failures + http.op_failures

    # Integrity guard: if a transport produced NO usable samples (every call failed, or the whole
    # post-warmup window erred), the percentile/median math below would crash on an empty list and
    # the harness would die mid-report instead of honestly declaring the operational failure. Report
    # the failure cleanly and bail — an empty dataset can never be a trustworthy latency number.
    if not (stdio.list_ms and stdio.call_ms and http.list_ms and http.call_ms):
        empty = [
            name
            for name, xs in (
                ("stdio tools/list", stdio.list_ms),
                ("stdio tools/call", stdio.call_ms),
                ("http tools/list", http.list_ms),
                ("http tools/call", http.call_ms),
            )
            if not xs
        ]
        print()
        print(f"  operational failures (separated from quality): {failures} / {total}")
        print(f"  RESULT: FAIL - no usable samples for: {', '.join(empty)} (all calls failed).")
        return 2

    print()
    print("GateKeeperAI - M3.1 HTTP transport overhead (HTTP vs stdio, same governed pipeline)")
    print("  real binary: `serve --transport <t>` subprocess | upstream = demo_file_server")
    print(f"  samples: tools/list {args.list_iters} (+{_LIST_WARMUP} warmup) | ", end="")
    print(f"tools/call {args.iters} (+{_CALL_WARMUP} warmup), per transport")
    print(f"  {'operation':<24} {'trans':<6} {'p50':>8} {'p95':>8} {'max':>8}  (ms)")
    print(_row("tools/list (no ledger)", "stdio", stdio.list_ms))
    print(_row("tools/list (no ledger)", "http", http.list_ms))
    print(_row("tools/call (governed)", "stdio", stdio.call_ms))
    print(_row("tools/call (governed)", "http", http.call_ms))

    # The gated quantity is the TRANSPORT-ISOLATION delta (tools/list, NO ledger): that is exactly
    # what the M3.1 budget bounds — "ASGI dispatch + localhost hop". Gating the governed-call delta
    # instead would measure the carried fsync baseline's tail jitter, not the transport (a category
    # error). The governed-call delta is reported as end-to-end context, p50 AND p95: on a shared
    # box its p95 is noise-dominated (the ~2x-fsync baseline amplifies GC/scheduling tails), so the
    # stable median is the honest per-call read.
    list_delta_p50 = statistics.median(http.list_ms) - statistics.median(stdio.list_ms)
    list_delta_p95 = _percentile(http.list_ms, 95) - _percentile(stdio.list_ms, 95)
    call_delta_p50 = statistics.median(http.call_ms) - statistics.median(stdio.call_ms)
    call_delta_p95 = _percentile(http.call_ms, 95) - _percentile(stdio.call_ms, 95)
    print()
    print(
        f"  HTTP - stdio delta (transport isolation, tools/list, GATED): "
        f"p50 {list_delta_p50:+.3f} ms | p95 {list_delta_p95:+.3f} ms"
    )
    print(
        f"  HTTP - stdio delta (governed call, end-to-end context, fsync-dominated): "
        f"p50 {call_delta_p50:+.3f} ms | p95 {call_delta_p95:+.3f} ms (p95 noise-dominated)"
    )
    print(f"  operational failures (separated from quality): {failures} / {total}")
    print(
        "  budget (config platform.yaml perf.http_transport_overhead_p95_ms): "
        f"transport-isolation p95 < {budget_ms:.1f} ms"
    )

    if failures:
        print("  RESULT: FAIL - operational failures occurred; latency numbers not trustworthy.")
        return 2
    if list_delta_p95 > budget_ms:
        print(
            f"  RESULT: FAIL - transport p95 delta {list_delta_p95:.3f} ms exceeds budget "
            f"{budget_ms:.1f} ms (aspirational miss; p50 {list_delta_p50:+.3f} ms). Re-measure on "
            "the Linux/SSD CI target before treating as canonical."
        )
        return 1
    print(
        f"  RESULT: PASS - transport p95 delta {list_delta_p95:.3f} ms within the "
        f"{budget_ms:.1f} ms budget."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
