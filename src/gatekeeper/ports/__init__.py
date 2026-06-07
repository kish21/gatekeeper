"""Ports — the adapter INTERFACES (typed Protocols). The hexagon's boundary.

One Protocol per external concern; concrete impls live in ``adapters/`` and are chosen by config:
    IdentityResolver   token -> principal + role
    PolicyEngine       (principal, action, resource) -> allow/deny + reason   (Cedar)
    LedgerStore        append + read + verify the tamper-evident chain
    UpstreamClient     forward a call to a real MCP server
    LLMProvider        (M2) text-in/score-out for risk classification
Defined in detail in /contracts. Business logic depends ONLY on these, never on a vendor SDK.
"""
