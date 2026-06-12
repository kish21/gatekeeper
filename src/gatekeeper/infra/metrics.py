"""In-process gateway metrics (M3.4) — counters + governance-overhead p95, Prometheus-rendered.

Deliberately dependency-free: a handful of counters and a bounded sample reservoir cover the
M3.4 exit criterion (calls, allow/deny rates, overhead p95 vs budget). The ``/metrics`` route
renders the standard Prometheus text exposition format, so both a curl-ing operator and a real
Prometheus scraper read the same surface; the LEDGER stays the authoritative audit record
(``gatekeeper stats`` derives history from it) — these metrics are the LIVE process view.

Single event loop (ADR-007) ⇒ plain attribute updates are not racy; no lock layer needed.
"""

from __future__ import annotations

from collections import Counter, deque


class GatewayMetrics:
    """Live counters for one gateway process. Recorded by the pipeline, read by ``/metrics``."""

    #: Overhead reservoir size: enough for a stable p95, bounded memory (~8 KB of floats).
    _RESERVOIR = 1024

    def __init__(self) -> None:
        self.calls_by_verdict: Counter[str] = Counter()
        self.identity_denies = 0
        self.forward_errors = 0
        self._overhead_s: deque[float] = deque(maxlen=self._RESERVOIR)

    # --- recording (called from the pipeline hot path; must stay trivial) ---------------------
    def record_call(self, verdict: str, overhead_s: float) -> None:
        self.calls_by_verdict[verdict] += 1
        self._overhead_s.append(overhead_s)

    def record_identity_deny(self) -> None:
        self.identity_denies += 1

    def record_forward_error(self) -> None:
        self.forward_errors += 1

    # --- reading -------------------------------------------------------------------------------
    def overhead_p95_ms(self) -> float | None:
        """p95 of recorded governance overhead, in ms. None until there is at least one sample.

        Nearest-rank on the sorted reservoir — same method as the /eval bench harness, so the
        live gauge and the offline measurement mean the same thing.
        """
        if not self._overhead_s:
            return None
        ordered = sorted(self._overhead_s)
        rank = max(0, min(len(ordered) - 1, round(0.95 * (len(ordered) - 1))))
        return ordered[rank] * 1000.0

    def prometheus_text(self, *, budget_ms: float) -> str:
        """Render the Prometheus text exposition (version 0.0.4 — the stable plain format)."""
        total = sum(self.calls_by_verdict.values())
        p95 = self.overhead_p95_ms()
        lines = [
            "# HELP gatekeeper_calls_total Governed tool calls by recorded verdict.",
            "# TYPE gatekeeper_calls_total counter",
            *(
                f'gatekeeper_calls_total{{verdict="{v}"}} {n}'
                for v, n in sorted(self.calls_by_verdict.items())
            ),
            "# HELP gatekeeper_identity_denies_total Calls denied as unauthenticated.",
            "# TYPE gatekeeper_identity_denies_total counter",
            f"gatekeeper_identity_denies_total {self.identity_denies}",
            "# HELP gatekeeper_forward_errors_total Allowed calls whose upstream forward failed.",
            "# TYPE gatekeeper_forward_errors_total counter",
            f"gatekeeper_forward_errors_total {self.forward_errors}",
            # p95 omitted entirely until there is a sample (no fake zero).
            *(
                [
                    "# HELP gatekeeper_overhead_p95_ms Governance overhead p95 (ms), live.",
                    "# TYPE gatekeeper_overhead_p95_ms gauge",
                    f"gatekeeper_overhead_p95_ms {p95:.3f}",
                ]
                if p95 is not None
                else []
            ),
            "# HELP gatekeeper_overhead_budget_ms Overhead budget (perf.overhead_p95_ms).",
            "# TYPE gatekeeper_overhead_budget_ms gauge",
            f"gatekeeper_overhead_budget_ms {budget_ms}",
        ]
        if total:
            deny_rate = self.calls_by_verdict.get("deny", 0) / total
            lines += [
                "# HELP gatekeeper_deny_rate Denied fraction of all governed calls.",
                "# TYPE gatekeeper_deny_rate gauge",
                f"gatekeeper_deny_rate {deny_rate:.4f}",
            ]
        return "\n".join(line for line in lines if line) + "\n"


#: Process-wide default registry — the pipeline records here unless a test injects its own.
default_metrics = GatewayMetrics()
