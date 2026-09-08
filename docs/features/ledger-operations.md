# Feature — Operating the ledger: export, retention, key rotation

> An audit store that cannot be exported, trimmed, or re-keyed is a prototype. These three
> operations each break a hash chain if done naively, so each one here is done in the way that
> keeps the chain meaningful.

## Export it to your SIEM

```bash
gatekeeper export --since 2026-01-01 --format cef --out audit.cef
gatekeeper export --since 2026-09-01 --until 2026-10-01 --format csv --out september.csv
gatekeeper export --format jsonl | your-shipper            # stdout by default
```

| Format | For |
|---|---|
| `jsonl` | one JSON object per entry — the full record, including the chain hashes |
| `csv` | a spreadsheet, or an auditor who asked for "the log" |
| `cef` | ArcSight CEF: the format most SIEMs ingest with no custom parser |

Streamed in batches, so exporting a year costs bounded memory and never holds one long
transaction open. Nothing is removed and nothing is changed — there is a test that the head hash
is identical afterwards.

The JSON-lines export carries `entry_hash` and `prev_hash`, so a copy in your SIEM is independently
checkable against the ledger it came from.

## Retention, without erasing the past

A hash chain proves nothing was removed. A retention policy exists to remove things. Pretending
that is not a conflict is how audit systems end up with a "cleanup" job that quietly makes deletion
undetectable.

```bash
gatekeeper archive --before 2026-01-01 --out 2025.jsonl              # copy them out
gatekeeper archive --before 2026-01-01 --out 2025.jsonl --prune \
                   --note "retention: 400 days"                       # and remove them
```

The archive file is always written first: a deletion with nowhere to read the records back from is
not retention, it is loss. Then the prune, in one locked transaction, records a **signed
checkpoint**:

- where the cut was (`through_seq`)
- what the chain stood at there (`through_hash`)
- how many records went, where they were archived, and why
- an HMAC of all of that, under the ledger key

`verify` resumes from the checkpoint instead of the genesis hash, and reports it:

```text
OK ledger intact - 3 entries verified
chain intact (resumed from a signed retention checkpoint: 4 records through seq 4
were archived on 2026-09-08)
```

The head hash does not change, so a head you pinned before the prune still matches after it.

What this buys you, tested three ways:

| Someone tries | What `verify` says |
|---|---|
| Deleting rows with no checkpoint | `TAMPERED … prev_hash linkage broken` |
| Editing the checkpoint (to understate what went) | `TAMPERED … the account of their removal was altered or forged` |
| Writing their own checkpoint after deleting rows | the same — they cannot compute its HMAC |

## Rotating the chain key

The chain key is a long-lived secret, and every security policy worth the name says long-lived
secrets get rotated. Until now rotating it made every existing record unverifiable, which is
another way of saying nobody rotated it.

```bash
gatekeeper rotate-key
```

Generates a new key, moves the current one into `GATEKEEPER_HMAC_KEY_PREVIOUS`, and writes both to
`.env`. Each entry stores a *fingerprint* of the key that signed it — a hash of the key, never the
key — so one `verify` walks a chain that spans the rotation:

```text
seq 1..3  key 1e564e30521a   (before)
seq 4..5  key e2f90d26ea55   (after)
verify -> OK ledger intact - 5 entries verified
```

Entries written before the gateway recorded fingerprints at all verify against any configured key,
so an existing ledger keeps working without rewriting a single stored record.

**Keep the retired keys.** Discarding one makes every record it signed unverifiable. That is
reported for what it is rather than as tampering —

```text
TAMPERED broken at seq=1: entry was signed with key '1e564e30521a', which is not
configured. Add it to GATEKEEPER_HMAC_KEY_PREVIOUS …
```

— but it cannot be undone.

## Checking it on a schedule

```bash
gatekeeper verify --json    # exit 0 intact, 1 tampered; the JSON is the evidence
```

Run it from cron or a monitoring check. The exit code is the alert; if `GATEKEEPER_ALERT_WEBHOOK`
is set, a failure also fires the webhook. Pin the printed head out of band and pass it back with
`--expect-head` to catch records removed from the *end* of the chain.

## Limits, stated

- **An archive file is an ordinary file.** Once records leave the ledger, their integrity is
  whatever your object store gives them. The checkpoint proves what was removed and where the
  chain stood; it does not protect the archive.
- **Rotation does not re-sign old records,** by design: re-hashing history with a new key would
  destroy the evidence that the old key ever signed anything.
- **Retention is manual.** There is no scheduler here; run `archive --prune` from cron with the
  window your policy requires, and keep the output.
