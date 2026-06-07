"""Ledger adapters (implement ports.LedgerStore), selected via config adapters.ledger.

hashchain.py — keyed-HMAC chain math (entry_hash = HMAC(key, prev_hash + canonical(entry))).
sqlite.py    — append-only SQLite store using the chain; powers `verify` (M1).
(postgres.py — deferred; same interface.)
"""
