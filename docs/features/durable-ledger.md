# Feature — Durable ledger (Postgres), and more than one replica

> Closes the M3.3 defect the first live Azure run found: governance held, but the audit trail did
> not survive the replica. It also lifts ADR-007's single-writer constraint, which is what pinned
> the hosted gateway to one replica.

## The problem this solves

The ledger was a SQLite file. On one machine that is the right answer — it is fast, it needs no
server, and `BEGIN IMMEDIATE` makes the hash chain safe against a second process.

On a hosted platform it fails in two different ways, and the live Azure run in August hit both:

| Where the file lived | What happened |
|---|---|
| The container's own disk | Correct while the replica ran, **gone** when Azure replaced it |
| An Azure Files (SMB) share | `audit.db` stayed at **0 bytes** while calls were served, a second process reported "Ledger table not found", and a restart lost every record. SMB does not give SQLite the locking and honest `fsync` it depends on |

Neither failure is loud. That is the worst property an audit store can have.

## What it is now

The same store, over either engine, chosen by configuration:

```bash
GATEKEEPER_LEDGER_URL=postgresql://user:password@host:5432/gatekeeper?sslmode=require
```

Set it and the ledger lives in that database; leave it unset and the ledger is the SQLite file at
`GATEKEEPER_LEDGER_PATH`. Nothing above the store changes — the pipeline, the CLI, the desk and
`verify` are one code path over both, which is why the SQLite tests keep covering the Postgres
deployment and vice versa.

- **Durable.** The records are in a managed database, not in a file the container owns. A replaced
  replica reads exactly what the previous one committed.
- **Readable from anywhere.** `gatekeeper tail`, `verify` and the desk work from any process or
  machine that can reach the database — including from your laptop against the hosted gateway.
- **Safe with many replicas.** An appending transaction takes a Postgres **transaction-scoped
  advisory lock** (`db/base.py:lock_chain`) before it reads the chain head, so two replicas can
  never read the same head and fork the chain. The lock is released by the commit or the rollback,
  so a replica that dies mid-append cannot wedge the chain, and it never blocks readers.
- **Bounded failure.** `lock_timeout` and `pool_pre_ping` are set, so a stuck peer or a connection
  the platform recycled becomes one failed (fail-closed, denied) call rather than a hung gateway.
- **Same migrations.** Alembic runs on both engines; a fresh database is migrated on first open,
  so a hosted deployment still has no separate migrate step.
- **The password never leaks.** Connection strings are redacted (`db/base.py:redact_url`) before
  they reach `doctor`, a log line, or an error message.

## Proven, not asserted

`tests/integration/test_ledger_postgres.py` runs against a real PostgreSQL (a service container in
CI; `GATEKEEPER_TEST_POSTGRES_URL` locally):

| Test | What it proves |
|---|---|
| `test_append_read_verify_on_postgres` | append / read / get / head / `verify --expect-head` behave exactly as on SQLite |
| `test_records_survive_the_process_that_wrote_them` | a NEW process on a NEW connection reads the chain back and verifies it — the inverse of the Azure defect |
| `test_concurrent_replicas_produce_one_intact_chain` | **six processes** appending at once produce ONE chain that verifies |
| `test_two_approvers_racing_one_request` | two people deciding the same held write: one wins, the other is refused |
| `test_open_ledger_uses_the_configured_url` | one environment variable moves the gateway onto Postgres — no code path is chosen by the caller |

The advisory lock is load-bearing, and that is measurable: with `lock_chain` stubbed out, the same
six-writer run breaks the chain (`verify` → `prev_hash linkage broken`, first break at seq 261 of
240 intended entries). With it, 240 of 240 verify.

## `doctor` will tell you before Azure does

A network-facing gateway still on the SQLite file is now a **failed** check, not a footnote:

```text
| ledger durability | FAIL | this gateway is network-facing but keeps its ledger in a local
                             SQLite file, which is lost when the container is replaced.
                             Set GATEKEEPER_LEDGER_URL to a Postgres database |
```

## Choosing

| | SQLite file | Postgres |
|---|---|---|
| One laptop, an MCP host launching the gateway | **Yes** — nothing to run | Overkill |
| One container you never replace | Works until it doesn't | Better |
| A hosted deployment, any real team | **No** | **Yes** |
| More than one replica | Not possible (one writer) | **Yes** |

## Limits, stated

- **Throughput is the chain's, not the database's.** Appends serialize by design: a hash chain has
  one head. That is a governance decision (one provable order of events), not an oversight. It
  bounds a single gateway deployment's write rate to what one serialized insert path sustains.
- **The database is now in the fail-closed path.** If Postgres is unreachable, appends fail and
  calls are denied — correct for an audit-before-act gateway, and it means the ledger database
  needs the availability you would give any control-plane dependency.
- **No cross-region story.** One database. A read replica does not help: the chain must be
  written in one place.
- **Retention still grows.** See `gatekeeper export` and the retention checkpoint in
  [ledger operations](ledger-operations.md).
