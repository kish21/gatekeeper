"""Error-reporter / tracing hook behind an adapter interface (ports & adapters).

A real deployment wires Sentry / OTel here; the default is a structured-logging reporter so nothing
is swallowed silently. Selected later via config; kept as a stub now so the seam exists from day one
(retrofitting observability is painful — ADR-004 resilience leans on it).
"""

from __future__ import annotations

from typing import Protocol

from gatekeeper.infra.logging import get_logger


class ErrorReporter(Protocol):
    """Port: report a handled error/event for observability. Impls must never raise."""

    def report(self, event: str, /, **fields: object) -> None: ...


class LoggingErrorReporter:
    """Default adapter: emit the event as a structured ERROR log. Never raises."""

    def __init__(self, logger_name: str = "gatekeeper.trace") -> None:
        self._log = get_logger(logger_name)

    def report(self, event: str, /, **fields: object) -> None:
        try:
            self._log.error(event, extra={"trace_event": event, **fields})
        except Exception:  # noqa: S110 — an observability hook must never take down the request path
            pass


#: Default reporter; swapped for Sentry/OTel via config in a later phase.
default_reporter: ErrorReporter = LoggingErrorReporter()
