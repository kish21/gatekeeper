"""Audit service — the wedge. Wraps the ledger port to append tamper-evident, hash-chained entries
and to ``verify`` the chain (recompute keyed-HMAC over each entry + its predecessor).

A failed verify pinpoints the first broken entry. Audit-before-act lives in the gateway pipeline;
the integrity math lives here.
"""
