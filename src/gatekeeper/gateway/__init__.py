"""Gateway pipeline — the Policy Enforcement Point (PEP).

Chain-of-responsibility over each tool call:
    identity -> policy(PDP) -> [M2: risk -> approval] -> audit-write -> forward
Fail-closed and audit-before-act (ADR-003): a call is recorded before it is forwarded, and any
error in a stage denies the call. Orchestration only — each capability is a port.
"""
