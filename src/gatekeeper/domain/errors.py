"""Typed, fail-closed errors raised across the gateway pipeline.

Each maps to a deny: identity that can't be resolved, or an upstream that can't be reached, must
NEVER fall through to an allow. Kept in ``domain`` (no I/O, no SDK) so every layer can raise/catch
them without an import cycle.
"""

from __future__ import annotations


class GatewayError(RuntimeError):
    """Base class for governance-pipeline failures (all fail-closed)."""


class IdentityError(GatewayError):
    """An opaque token could not be resolved to a Principal — the call is unauthenticated."""


class PolicyDenied(GatewayError):
    """The policy engine denied this (principal, call) — RBAC said no. Recorded, never forwarded."""


class UpstreamError(GatewayError):
    """A registered upstream could not be reached or returned a transport-level failure."""
