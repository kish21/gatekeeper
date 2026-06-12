# Feature — HTTP transport (M3.1)

> Build #6 · 2026-06-12 · finishes the M1 in-scope item *"Transparent MCP proxy (stdio + **HTTP**
> transport)"*. Architecture decisions: `PRODUCT.md#Architecture` → *M3.1 addendum* (ADR-007/008/009).

## What it is

A network-reachable binding of the **same governed pipeline**: an agent speaks **MCP Streamable
HTTP** (the current spec transport, via the official SDK's `StreamableHTTPSessionManager`) to a
FastAPI + uvicorn app, and every `tools/call` runs the identical chain —
`identity → classify → policy(Cedar) → audit-before-act → forward → audit` — into the same
tamper-evident ledger as stdio. `gatekeeper serve --transport http` (or `transport.mode: http`).

**New capability vs stdio:** per-request identity. stdio binds one `$GATEKEEPER_AGENT_TOKEN` to
the process; HTTP reads `Authorization: Bearer <token>` **per request**, so many principals share
one gateway, each call resolved + recorded under its own caller (ADR-008).

## How it holds the invariants

| Invariant | How |
|---|---|
| One proxy surface, no transport drift | `transport/surface.py` builds the tool index + list/call handlers ONCE; stdio (`stdio_server.py`) and HTTP (`http_server.py`) are thin bindings of it. |
| Transport stays logic-free (ADR-008) | The transport only **extracts** the bearer from the SDK request context (`extract_bearer_token`); the **pipeline** resolves + records it. A missing/forged bearer on `tools/call` still reaches the pipeline → ledgered identity-deny (`<unauthenticated>`/DENY) → refused. Never a silent transport-level 401. |
| No unauthenticated enumeration | `tools/list` resolves the token fail-closed; an unauthenticated caller gets an **empty list**. Empty-not-raise is load-bearing: the SDK's `call_tool` wrapper refreshes its tool cache through the list handler, and a raise there would short-circuit the ledgered deny above (found by `test_http_unauthenticated_is_fail_closed_and_ledgered`). |
| Ledger single-writer held by construction (ADR-007) | Programmatic `uvicorn.Server` = one process / one event loop; the sync ledger append contains no `await`, so appends cannot interleave. **No `workers` knob exists**; M3.3 deploys 1 replica. |
| Fail-closed exposure (ADR-009) | Default bind `127.0.0.1:8765`; a non-loopback `transport.http_host` **refuses boot** unless `transport.http_allow_non_loopback: true`, which logs the ADR-006 bearer-replay warning. Unknown hostnames count as non-loopback (refuse rather than resolve-and-guess). SDK DNS-rebinding protection stays ON (loopback Host set + `transport.http_allowed_origins`, empty default ⇒ cross-site Origins refused). TLS terminates at the cloud ingress (M3.3), not in-process. |
| No secrets in config/code | The bearer arrives in a request header only; nothing token-shaped lands in YAML, code, or logs. |

## Contract

- **Config (`config/platform.yaml`, all knobs read at boot — no hardcoding):**
  `transport.mode` (stdio|http) · `http_host` · `http_port` · `http_path` (default `/mcp`) ·
  `http_allow_non_loopback` (default `false`) · `http_allowed_origins` (default `[]`).
  CLI override: `gatekeeper serve --transport stdio|http`. Unknown transport ⇒ exit 2 (fail-loud).
- **In:** MCP Streamable HTTP at `http_path` (GET=SSE stream, POST=JSON-RPC, DELETE=session end),
  `Authorization: Bearer <token>` per request. Exact-path route (a Starlette `Mount` would
  307-redirect `/mcp → /mcp/`, which not every MCP client follows).
- **Out:** the upstream's untouched `CallToolResult` (transparent relay), or `isError=true` with
  `denied: …` for identity/RBAC refusals. `/healthz` → `{"status":"ok"}` (liveness for the M3.3
  container probe; deliberately unauthenticated and state-free).

## Exit criterion (PRODUCT.md `#Plan` M3.1) — how verified

| Criterion | Evidence |
|---|---|
| Agent governs calls over HTTP (loopback) through the same pipeline | `tests/integration/test_http_transport.py::test_http_calls_run_the_same_pipeline_and_verify_clean` — real uvicorn + real MCP client + real subprocess upstream: transparent read-back, RBAC deny ledgered, PII stance held. **Live:** `gatekeeper serve --transport http` driven by an MCP client — healthz 200, 6 tools across both upstreams (incl. the third-party `time` server), alice read allowed, bob write `denied … (default-deny)`. |
| stdio unchanged | Full suite green (150 passed) incl. all prior stdio/proxy integration tests, now through the shared surface. |
| Calls over both transports recorded + `verify`-clean | Live ledger holds prior stdio entries (seq 2–4) and this session's HTTP entries (seq 5–7) in ONE chain; `gatekeeper verify` → `OK ledger intact - 7 entries verified`. |
| ADR-006 trigger documented *and enforced* at the boundary | `ensure_exposure_acked` refuses a non-loopback bind without the explicit ack (unit-parametrized); the ack path logs the bearer-replay warning. ADR-006 itself stays deferred (still loopback-only); re-evaluate at M3.2/M3.3. |

Adversarial coverage: forged bearer over HTTP ⇒ ledgered `<unauthenticated>` DENY + `denied:` error
(`test_http_unauthenticated_is_fail_closed_and_ledgered`); rebound Host header ⇒ 421 before the MCP
surface (`test_http_rejects_unknown_host_header`).

## Code

- [src/gatekeeper/transport/surface.py](../../src/gatekeeper/transport/surface.py) — shared governed surface (index + handlers + `TokenProvider` seam).
- [src/gatekeeper/transport/http_server.py](../../src/gatekeeper/transport/http_server.py) — Streamable HTTP binding, exposure guard, bearer extraction, app factory, single-worker serve.
- [src/gatekeeper/transport/stdio_server.py](../../src/gatekeeper/transport/stdio_server.py) — stdio binding (now ~45 lines, surface-backed).
- [src/gatekeeper/cli/app.py](../../src/gatekeeper/cli/app.py) — `serve --transport`.
- Tests: [tests/unit/test_http_seams.py](../../tests/unit/test_http_seams.py) · [tests/integration/test_http_transport.py](../../tests/integration/test_http_transport.py).

## Known limitations (deliberate, recorded)

- **Bearer tokens remain replayable** if exfiltrated — acceptable on loopback (ADR-006 deferred);
  the non-loopback ack exists precisely to make wider exposure a recorded decision. OIDC (M3.2)
  and the deploy guide (M3.3) revisit this.
- **Transport-overhead budget is aspirational** (+<~5 ms p95 over stdio on loopback) — derived,
  not yet measured; re-measure with the `bench_governance_latency.py` pattern in the M3 `/eval`.
- `initialize` itself is unauthenticated (protocol handshake, reveals only server name/version);
  the governed surface (`tools/list`, `tools/call`) is where fail-closed auth applies.
