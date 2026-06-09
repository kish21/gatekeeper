# Feature: Tamper-evidence gate + `show` (M1.3)

**Status:** built · verified · documented. Closes Milestone 1 slice **M1.3**.

## What it does
M1.3 is the **gate** that confirms the wedge — tamper-evidence — still holds now that the ledger records
**RBAC allow/deny verdicts** (M1.2), and it adds the operator command to inspect a single recorded
decision:

- **`gatekeeper verify`** — walks the keyed-HMAC hash-chain, passes on an intact ledger and **pinpoints the
  exact `seq`** when any record is altered, deleted, reordered, inserted, or signed with the wrong key.
  (Chain mechanics live in [`ledger.md`](ledger.md); M1.3 re-verifies them against the RBAC pipeline.)
- **`gatekeeper show <call_id>`** — loads one audit entry by `call_id` and renders the recorded governance
  decision (verdict, reason, principal+role, tool, action, timestamp, chain hashes, redacted result).

`show` and `verify` are complementary: **`show` reads what was recorded; `verify` proves it wasn't forged.**
A row whose `deny` is tampered to `allow` will still *display* via `show`, but `verify` flags the chain as
broken at that `seq` — the forgery cannot hide.

## Contract (in/out)
- **Reuses** the existing typed `ports.ledger.LedgerStore` — `verify() -> VerifyResult`, `get(call_id) -> LedgerEntry | None`.
  No new port method was added.
- **`show` CLI:** `gatekeeper show <call_id>` → exit **0** found · **1** no entry for that call_id · **2** misconfig.
  Renders via `box.ASCII` (legacy-Windows-console safe). `call_id` is bound as a query parameter by the ORM (no injection).
- **`verify` CLI:** exit **0** intact / **1** tampered / **2** misconfig; prints the head hash for out-of-band pinning.

## Definition of done — incl. security (met)
- [x] **M1.3 exit criterion:** hash-chained entries; `verify` passes intact and **fails pinpointing the
      entry** on alter/insert/remove — confirmed live on a ledger holding **RBAC allow + deny verdicts**.
- [x] `show` renders the full recorded decision for both an **allowed** and a **denied** call.
- [x] **Fail-closed / fail-loud:** `show` reuses `_opened_ledger()` → misconfig (no HMAC key / no table) exits **2**,
      never a silent insecure read.
- [x] **No secret/token leak:** the entry holds `principal`/`role` (never the bearer token) and HMAC digests
      (never the HMAC key, which lives only in `.env`) — asserted by `test_show_never_leaks_token_or_key`.
- [x] **PII-safe by construction:** only `payload_hash` + redacted `result_summary` exist to display; raw
      arguments/output are never persisted.
- [x] **No injection:** `call_id` flows only into a parameterized SQLAlchemy `where`.
- [x] **Reuse, no reinvention:** `_opened_ledger`, `open_ledger`, `LedgerStore.get`, `Verdict`, `box.ASCII`.
- [x] No secret in code (tests use a fake `"k"*64` / `"a"*64` key).

## How it was verified (evidence)
- **Live path (real `gatekeeper` CLI + real SQLite, RBAC verdicts):**
  - seed 2 entries through the real `LedgerStore.append` chain — `alice/operator write → ALLOW`, `bob/readonly write → DENY`.
  - `gatekeeper tail` → both verdicts; `gatekeeper show <allow>` and `show <deny>` → full decision tables
    (the deny's `prev_hash` visibly equals the allow's `entry_hash` — chain linkage shown).
  - `gatekeeper show does-not-exist` → `not found`, **exit 1**.
  - `gatekeeper verify` → `OK ledger intact - 2 entries verified` + head hash, **exit 0**.
  - raw-SQL tamper (flip `seq=2` `deny`→`allow`) → `gatekeeper verify` = `TAMPERED broken at seq=2:
    entry_hash mismatch`, **exit 1**; `show` still renders the altered row (proving the read/verify split).
- **Tests (82 total; 5 new in `tests/unit/test_cli_show.py`):** show found-allow, found-deny, not-found→exit 1,
  never-leaks-token-or-key, legacy-Windows-console-safe. Chain/tamper unit+integration tests from M1 still green.
- **Reviews:** `/code-review` (high) → no findings (exit codes, parameterized query, ctx-manager close,
  nullable-field guards all confirmed). `/security-review` → no **new** vuln ≥ conf 8.
- **Static:** ruff + ruff-format + mypy (strict) clean (47 source files).

## Known limitations (honest)
- **`show`/`get(call_id)` is not tenant-scoped** — consistent with `tail` (both are single-tenant M1 operator
  tools; the operator already has full file access to the ledger). `/security-review` flagged this as the
  pre-existing, documented limitation tied to the **deferred multi-tenant trigger** (PRODUCT.md#Scope), not a
  new exposure. When multi-tenant lands, tenant-scope `get()`, `read()`, and `show` together.
- **Tail-truncation** (deleting the newest N entries) is undetectable by a bare chain — mitigated by `verify`
  emitting the head hash for out-of-band pinning; full anchoring deferred. (See [`ledger.md`](ledger.md).)

## Code
- `src/gatekeeper/cli/app.py` — `show` (new) · `verify` / `tail` · `_opened_ledger()`.
- `src/gatekeeper/adapters/ledger/sqlite.py` — `SqliteLedgerStore.get` / `verify` (reused).
- `tests/unit/test_cli_show.py` — the `show` CLI tests.
- Chain mechanics + ledger DoD: [`ledger.md`](ledger.md).
