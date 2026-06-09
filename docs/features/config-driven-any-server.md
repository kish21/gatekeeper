# Feature: Config-driven any-server + operator CLI (M1.4)

**Status:** built · verified · documented. Closes Milestone 1 slice **M1.4** (the M1 exit slice).

## What it does
M1.4 is the slice that proves the product's tool-agnostic promise and finishes the operator surface:

1. **Govern ANY MCP server by config alone (zero gateway code).** A second, *different* MCP server —
   the **real, third-party `mcp-server-time`** (a server we did **not** write) — is brought under full
   governance (identity → RBAC → tamper-evident audit) purely by adding a block to
   [`config/upstreams.yaml`](../../config/upstreams.yaml) and installing its package via the `demo`
   extra. **No `src/gatekeeper/` change** routes, classifies, or audits it — the existing pipeline does.
2. **`gatekeeper seed-demo`** — the last operator command (was a stub). A non-destructive helper that
   prepares the local demo (seeds the `demo_file_server` sandbox + a sample file) and prints the exact
   run recipe, reading the committed config back so you can see what is governed.
3. **Resilience hardening (found on the live path):** one unavailable/misconfigured upstream is now
   **logged and skipped** instead of crashing the whole gateway — essential once "add any server by
   config" is real (a typo in one entry must not take governance down for the others).

## Contract (in/out)
- **`config/upstreams.yaml`** is the registry. Each entry: `name`, `transport` (`stdio`), `command`
  (how to launch), and optional `reads`/`writes` annotations that drive read/write classification.
  Adding a server = adding a block here. (HTTP transport is a documented fast-follow; see
  `UpstreamSpec.stdio_params`.)
- **`gatekeeper seed-demo`** → exit **0** (prepared + recipe printed) · **2** if the config dir is
  missing (fail-loud). Does **not** require the HMAC key (it is a setup helper, not a governance op)
  and does **not** overwrite committed config. Prints **principal + role only — never the bearer token**.
- **Reuses** `load_config`, `get_settings`, `box.ASCII` rendering, and the existing pipeline / adapters
  unchanged. No new port or schema was added.

## Definition of done — incl. security (met)
- [x] **M1.4 exit criterion:** a second, different MCP server is governed by **editing config only
      (zero `src/gatekeeper/` code)** — proven live and by an integration test against the real
      `mcp-server-time` subprocess.
- [x] The governed third-party call is **authenticated → RBAC-decided (read → allow) → transparently
      relayed → recorded** as two chained ledger entries; `verify` passes; the Cedar reason names the
      new server's resource (`time::get_current_time`).
- [x] **`seed-demo` implemented**, non-destructive + idempotent; fail-loud (exit 2) on missing config.
- [x] **No secret/token leak:** `seed-demo` prints roles, never tokens (asserted by a test); the
      `demo` dependency is a *governed target*, not a gateway runtime dep.
- [x] **Availability:** a single bad upstream is isolated (logged + skipped), never fatal — and skipping
      it exposes **no ungoverned bypass** (its tools simply aren't published).
- [x] **Windows-console-safe:** all `seed-demo` output is pure ASCII (`box.ASCII`, no smart punctuation);
      `[demo]` is printed with `markup=False` so it isn't eaten as a Rich tag.
- [x] ruff + ruff-format + mypy (strict) clean; `/code-review` + `/security-review` clean.

## How it was verified (evidence)
- **Live path (real `gatekeeper serve` ← real MCP client → real third-party server):** with the `time`
  upstream in config, `serve` started, listed **6 tools** across both upstreams
  (`convert_time, delete_file, get_current_time, list_dir, read_file, write_file`), and a client call to
  `get_current_time` returned the real server's untouched JSON. `gatekeeper tail` showed
  `time:get_current_time` / `time:convert_time` as **allow**; `gatekeeper verify` → `OK ledger intact`;
  `gatekeeper show <call_id>` → full decision (`time:get_current_time`, read, allow, *"allowed by cedar
  policy: role 'operator' may read time::get_current_time"*).
- **Live `seed-demo`:** rendered both governed upstreams + identities (roles only) + the 5-step recipe;
  seeded `.gatekeeper/demo_sandbox/welcome.txt`.
- **Tests (91 total; 9 new):**
  - `tests/integration/test_any_server.py` — governs the real third-party server end-to-end (allow +
    audited + `verify` ok + Cedar reason names the resource) and lists its tools. Skips gracefully if
    the `demo` extra isn't installed; **CI installs `.[demo]` so it runs for real on every push.**
  - `tests/unit/test_cli_seed_demo.py` — sandbox+sample created, recipe shown, idempotent, fail-loud on
    missing config, **no token leak**, pure-ASCII output, sandbox default matches the demo server.
  - `tests/integration/test_proxy.py::test_one_bad_upstream_does_not_take_down_the_gateway` — the
    resilience fix.
- **Static / reviews:** ruff + format + mypy (strict) clean (49 source files); `/code-review` and
  `/security-review` recorded in `PRODUCT.md#Build log`.

## Known limitations (honest)
- **stdio transport only this slice.** An upstream declaring `transport: http` raises a clear
  `NotImplementedError` (HTTP is a documented fast-follow). Both M1 demo targets are stdio.
- **The `command`'s interpreter must resolve to one that has the server's package.** In the demo,
  `command: ["python", ...]` relies on the `python` on PATH having `mcp-server-time` (e.g. an activated
  venv). For a hardened deployment, pin an absolute interpreter path or set `env`/`cwd` in the entry.
  Note the interaction with the resilience skip: a launch failure here is now **logged and skipped**,
  not fatal — so a misconfigured interpreter shows up as "that upstream's tools just aren't exposed"
  (visible in the `gateway ready` log's tool list and the `upstream unavailable; skipping` error log),
  and the skip is **latched until the next gateway restart** (no boot-time retry of a dead upstream).
- Inherited single-tenant `get()` scoping limitation (see [`tamper-evidence.md`](tamper-evidence.md)),
  tied to the deferred multi-tenant trigger — unchanged by this slice.

## Code
- `config/upstreams.yaml` — the `time` (third-party) registry entry.
- `pyproject.toml` — `[project.optional-dependencies] demo` (the governed-target package).
- `.github/workflows/ci.yml` — installs `.[demo]` so the any-server proof runs in CI.
- `src/gatekeeper/cli/app.py` — `seed-demo` (implemented) + helpers.
- `src/gatekeeper/transport/stdio_server.py` — `_build_tool_index` resilience (skip a bad upstream).
- `tests/integration/test_any_server.py`, `tests/unit/test_cli_seed_demo.py`,
  `tests/integration/test_proxy.py` (resilience case).
