# Feature: Tamper-evident audit ledger (M1)

**Status:** built · verified · documented. The wedge of GateKeeperAI.

## What it does
An append-only, keyed-HMAC **hash-chained** audit store, plus the `verify` and `tail` CLI commands.
Every record is cryptographically linked to the previous one, so any alteration, mid-chain deletion,
reordering, or insertion is detected — and `verify` pinpoints the exact entry where the chain breaks.

```
append(e):  prev = last.entry_hash (or GENESIS)
            e.entry_hash = HMAC-SHA256(key, prev + canonical_json(e))   # key from .env
verify():   walk seq ascending; recompute each entry_hash; check prev_hash linkage
```

## Contract (in/out)
- **Port:** `ports.ledger.LedgerStore` → `append`, `read`, `get`, `verify`.
- **Types:** `schemas.ledger.LedgerEntry` (in/out), `VerifyResult` (verify out). `prev_hash`/`entry_hash`
  are store-computed (optional on input, always set on output).
- **Persistence:** `ledger_entry` table (migration `0001_create_ledger`); `append` is the only writer.
- **CLI:** `gatekeeper verify` (exit **0** intact / **1** tampered / **2** misconfig) prints the **head hash**
  for external pinning; `gatekeeper tail [--limit] [--principal]`.

## Definition of done — incl. security (met)
- [x] Append-only (no update/delete API); the only write path is `append`.
- [x] **Fail-closed:** the HMAC key is required at boot (`validate_security`); `open_ledger()` routes
      through `boot()`, so no command can skip the guard. Missing/weak key → no run.
- [x] Tamper-evidence catches: field edit, mid-chain delete, reorder, insert, **and wrong key**.
- [x] Keyed HMAC-SHA256; unambiguous concatenation (`prev_hash` is fixed 64-hex); deterministic
      canonical JSON (sorted keys, enums-as-values, `schema_version` inside the hash).
- [x] **No secret in code** (tests use a fake `"k"*64` key); key only from `.env`.
- [x] PII: only `payload_hash` + redacted `result_summary` are stored — never raw args/output.
- [x] Tenant/owner filter on `read(principal=…)`.

## How it was verified (evidence)
- **Live path (real CLI + real SQLite):** migrate → append 3 → `verify` = `OK … 3 entries verified` +
  head hash (exit 0) → edit a row via raw SQL → `verify` = `TAMPERED broken at seq=2` (exit 1).
- **Tests (29 total; 9 new):** `tests/unit/test_hashchain.py` (determinism, key/prev/content sensitivity),
  `tests/integration/test_ledger.py` (chaining, verify-ok, field-tamper→seq, deletion→seq, wrong-key, read/get/tenant).
- **Reviews:** `/security-review` → no findings ≥ conf 8. `/code-review` → cleanups applied (shared
  `ledger_path` helper, `opened_ledger` context manager, model-derived row insert).
- **Static:** ruff + mypy clean; `alembic check` = no drift.

## Known limitations (honest)
- **Tail-truncation:** a bare hash-chain cannot detect deletion of the *newest* N entries (the remaining
  prefix still verifies). Mitigation in place: `verify` emits the **head hash** so it can be pinned
  out-of-band; full mitigation (periodic anchoring / external checkpoint) is a future enhancement.
- **`get(call_id)` is not tenant-scoped.** Safe today (`call_id` is a UUID4, single-tenant), but add a
  tenant filter when multi-tenant lands (deferred per Scope).
- **Single-writer assumption:** `append` chains off the current max-seq row; concurrent writers could
  fork the chain. Fine for the single gateway process; revisit if appends become concurrent.

## Code
- `src/gatekeeper/adapters/ledger/hashchain.py` — pure HMAC chain math.
- `src/gatekeeper/adapters/ledger/sqlite.py` — `SqliteLedgerStore` (append/read/get/verify).
- `src/gatekeeper/adapters/ledger/factory.py` — `open_ledger()` (fail-closed + fail-loud).
- `src/gatekeeper/cli/app.py` — `verify` / `tail` + `_opened_ledger()`.
