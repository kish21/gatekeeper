"""Alert hook (M3.4) — one fail-safe webhook for operator-grade signals.

Two wired signals (the M3.4 exit criterion's "one alert hook", applied to both places the plan
names): **verify-failure** (the CLI detected ledger tampering) and **deny-spike** (an unusual
burst of denies — a probing agent or a broken policy rollout).

Fail-SAFE by contract: alerting must never take down (or block) the governed path — every
network failure is swallowed into a structured log line. The webhook URL lives in ``.env``
(``GATEKEEPER_ALERT_WEBHOOK``) because such URLs routinely embed tokens (Slack/Teams/PagerDuty);
unset ⇒ alerting is off and detectors stay silent. Fail-safe-not-closed is deliberate: alerts
are a SIGNAL channel, not a control; governance itself stays fail-closed in the pipeline.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

import httpx

from gatekeeper.infra.logging import get_logger

_POST_TIMEOUT_S = 5.0


class WebhookAlerter:
    """POST one JSON alert to the configured webhook. Never raises."""

    def __init__(self, url: str, *, timeout_s: float = _POST_TIMEOUT_S) -> None:
        self._url = url.strip()
        self._timeout = timeout_s
        self._log = get_logger("gatekeeper.alerts")

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def fire(self, kind: str, detail: dict[str, Any]) -> bool:
        """Send {kind, detail, ts}. Returns True when delivered (used by tests/operators)."""
        if not self.enabled:
            return False
        payload = {"source": "gatekeeper", "kind": kind, "ts": time.time(), "detail": detail}
        try:
            response = httpx.post(self._url, json=payload, timeout=self._timeout)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 — alerting is fail-safe, never fail-loud
            # The URL is not logged (it may embed a token); the alert content is.
            self._log.error(
                "alert webhook delivery failed",
                extra={"kind": kind, "error": type(exc).__name__},
            )
            return False
        self._log.info("alert fired", extra={"kind": kind})
        return True


class DenySpikeDetector:
    """Sliding-window deny counter: True exactly once per breach episode (no alert storms).

    ``record_deny`` returns True when the count of denies inside ``window_s`` crosses
    ``threshold``; it then stays quiet until the window has drained below the threshold and a
    NEW breach happens (re-arm), so a sustained attack yields one alert per episode.
    """

    def __init__(self, *, window_s: float, threshold: int) -> None:
        if window_s <= 0 or threshold <= 0:
            raise ValueError("deny_spike window_s and threshold must be positive")
        self._window = window_s
        self._threshold = threshold
        self._denies: deque[float] = deque()
        self._fired = False

    def record_deny(self, now: float | None = None) -> bool:
        ts = time.monotonic() if now is None else now
        self._denies.append(ts)
        while self._denies and ts - self._denies[0] > self._window:
            self._denies.popleft()
        breached = len(self._denies) >= self._threshold
        if breached and not self._fired:
            self._fired = True
            return True
        if not breached:
            self._fired = False  # window drained -> re-arm for the next episode
        return False

    @property
    def current_count(self) -> int:
        return len(self._denies)
