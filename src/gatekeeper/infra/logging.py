"""Structured (JSON) logging — the observability spine. No stray ``print`` anywhere in prod paths.

JSON lines are SIEM-friendly (the audit ledger is the *durable* record; logs are the operational
stream). Uses only the standard library so the walking skeleton stays dependency-light.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

_RESERVED = frozenset(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Render a log record as a single JSON object, including any structured ``extra`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():  # promote structured extras
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger. Idempotent (safe to call per command)."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
