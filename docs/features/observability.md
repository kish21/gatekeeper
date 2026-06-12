# Feature — Observability surface (M3.4)

> Build #9 · 2026-06-12 · `#Learnings` watch item *"a live usage dashboard / alerting — trigger:
> a real deployment"* fired by M3.3. CLI-first product ⇒ the surface is `/metrics` + `stats` +
> one alert hook — NOT a web dashboard (that stays deferred with its own trigger).

## What an operator gets

| Surface | What it shows | Where it reads from |
|---|---|---|
| **`GET /metrics`** (HTTP transport) | Prometheus text exposition: `gatekeeper_calls_total{verdict=…}`, `gatekeeper_identity_denies_total`, `gatekeeper_forward_errors_total`, `gatekeeper_deny_rate`, **`gatekeeper_overhead_p95_ms` vs `gatekeeper_overhead_budget_ms`** (the configured `perf.overhead_p95_ms`) | live in-process registry ([infra/metrics.py](../../src/gatekeeper/infra/metrics.py)) recorded by the pipeline |
| **`gatekeeper stats`** (any transport) | calls · allowed/denied counts + rates · denies by principal · busiest tools · time window — each call counted **once** (its decision entry) | the **ledger** (authoritative history; pair with `verify` to prove it untampered) |
| **Alert hook** (`GATEKEEPER_ALERT_WEBHOOK` in `.env`) | one JSON POST on **`verify_failure`** (CLI found tampering — the signal this product exists for) and on **`deny_spike`** (≥ `observability.deny_spike.threshold` denies inside `window_s`; one alert per breach episode, re-arms when the window drains) | `verify` CLI + the pipeline via [infra/alerts.py](../../src/gatekeeper/infra/alerts.py) |

**Design decisions (mini-architect, benchmarked 2026):**
- **No new dependency.** The exposition format is the stable Prometheus text format — both a
  `curl`-ing operator and a real Prometheus/Grafana/Azure-Monitor scraper read it. A
  `prometheus-client` dependency would still not compute an in-process p95 (that needs the
  reservoir we keep anyway).
- **Overhead p95 measures the same quantity as the `/eval` bench** (everything except the upstream
  forward; nearest-rank percentile) — so the live gauge and the offline measurement agree by
  construction, honoring the harvested rule *"derive budgets from measured cost"*.
- **Alerting is fail-SAFE, not fail-closed** (deliberate): alerts are a signal channel, not a
  control — a down Slack webhook must never block or fail a governed call. Delivery happens off
  the hot path (worker thread, fire-and-forget); failures become one structured log line. The
  webhook URL lives in `.env` because such URLs routinely embed tokens; it is never logged.
- **/metrics exposes aggregates only** — no principals, tools-with-arguments, or tokens (asserted
  by test), so liveness-level exposure is acceptable; per-call records stay in the ledger.

## Config (no hardcoding)

```yaml
# platform.yaml
observability:
  deny_spike: { window_s: 60, threshold: 10 }
perf:
  overhead_p95_ms: 10.0        # the budget the p95 gauge is compared against
```
```bash
# .env (optional; unset = alerting off)
GATEKEEPER_ALERT_WEBHOOK=https://hooks.slack.com/services/…
```

## How verified

- **Unit ×11** ([tests/unit/test_observability.py](../../tests/unit/test_observability.py)):
  p95 nearest-rank correctness + render shape (incl. "no samples ⇒ no fake zero gauge") ·
  spike detector fires once per episode and re-arms · alerter disabled-without-URL, payload
  shape, fail-safe on receiver outage · REAL `pipeline.handle` runs recording allow/deny/
  identity-deny counters + overhead and firing exactly one spike alert · `stats` CLI vs a seeded
  real SQLite ledger (counts each call once, rates, cp1252-safe) and on an empty ledger.
- **Integration (live HTTP):** `/metrics` after real governed calls shows `calls_total`,
  `overhead_p95_ms`, `budget_ms` — and contains **no principal and no token**
  ([test_http_transport.py](../../tests/integration/test_http_transport.py)).
- **Live container:** `curl /metrics` against the running image (see the M3.3 doc).

## Recorded limitations

- Metrics are **per-process and reset on restart** (standard Prometheus counter semantics;
  rates/deltas are the scraper's job). The ledger remains the durable history — `stats` covers it.
- `stats` derives from the last `--limit` entries (default 1000) — a window, not an all-time scan
  (full analytics belongs to SIEM ingestion of the JSON logs / ledger, already supported).
- The deny-spike detector is in-process: a restart clears the window (acceptable at single-replica
  scale, ADR-007; platform-level alerting can also scrape `gatekeeper_deny_rate`).
