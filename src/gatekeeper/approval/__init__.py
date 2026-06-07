"""M2 — human-in-the-loop write-approval gate.

Holds a risky/write call pending a human approve/deny decision, then records the approver identity
+ outcome in the verifiable ledger. Fail-closed: no approval within the timeout -> deny (ADR-005).
"""
