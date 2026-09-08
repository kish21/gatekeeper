"""Telling a person that a write is waiting for them.

A hold that nobody hears about is just a slow denial. The gateway can stop a write and record the
decision perfectly, and it is still useless if the only way to learn a write is waiting is to have
the desk open in a tab at the right moment.

So when a write is held, one message goes to wherever the approvers already are — a Slack or Teams
incoming webhook — saying who asked, what the call would do, how long is left, and where to decide
it. A second message follows the decision, so the thread ends with an answer instead of silence.

Two properties this file exists to guarantee:

  * **It cannot slow down or break a governed call.** Delivery is fire-and-forget on a worker
    thread and every failure becomes a log line. Notification is a signal channel, never a control:
    if Slack is down, the write still waits for a human and still times out into a deny.
  * **It does not leak into the message what the ledger refuses to store.** The preview is the
    same bounded, truncated argument preview the desk shows an approver — never the raw payload.

Payload shape is deliberately plain: ``text`` is what Slack and Teams both render, and the
structured fields ride alongside for anything else consuming the hook.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from gatekeeper.infra.logging import get_logger
from gatekeeper.schemas.approval import ApprovalRequest
from gatekeeper.schemas.enums import ApprovalStatus

_POST_TIMEOUT_S = 5.0
#: Arguments shown in a chat message. Shorter than the desk's preview: chat is for deciding to go
#: and look, not for reading a payload.
_PREVIEW_IN_MESSAGE = 200

_STATUS_WORD = {
    ApprovalStatus.APPROVED: "approved",
    ApprovalStatus.DENIED: "denied",
    ApprovalStatus.EXPIRED: "timed out (counted as denied)",
    ApprovalStatus.CANCELLED: "cancelled — the caller gave up waiting",
}


@dataclass(frozen=True)
class ApprovalNotifier:
    """Posts held-write notifications to one incoming webhook. Never raises, never blocks."""

    url: str = ""
    #: Where a person can go to decide, e.g. ``https://gatekeeper.corp.example/ui``. Put in the
    #: message so the notification is actionable rather than merely informative.
    desk_url: str = ""
    timeout_s: float = _POST_TIMEOUT_S

    @property
    def enabled(self) -> bool:
        return bool(self.url.strip())

    def held(self, request: ApprovalRequest, *, timeout_s: float) -> dict[str, Any]:
        """The message for a write that is now waiting for a person."""
        preview = request.arguments_preview[:_PREVIEW_IN_MESSAGE]
        where = f"\nDecide at {self.desk_url}" if self.desk_url else ""
        return {
            "text": (
                f"⏸ *{request.principal}* ({request.role}) wants to run "
                f"*{request.upstream}:{request.tool}* — waiting for a human.\n"
                f"`{preview}`\n"
                f"Request `{request.id}` · {timeout_s:g}s to decide, then it is denied.{where}"
            ),
            "event": "approval.held",
            "request_id": request.id,
            "principal": request.principal,
            "role": request.role,
            "tool": f"{request.upstream}:{request.tool}",
            "call_id": request.call_id,
            "timeout_s": timeout_s,
            "desk_url": self.desk_url,
        }

    def decided(self, outcome: ApprovalRequest) -> dict[str, Any]:
        """The message that closes the loop: what happened, and who decided it."""
        word = _STATUS_WORD.get(outcome.status, outcome.status.value)
        icon = "✅" if outcome.status is ApprovalStatus.APPROVED else "⛔"
        who = f" by *{outcome.decided_by}*" if outcome.decided_by else ""
        how = f" ({outcome.decided_method})" if outcome.decided_method else ""
        note = f"\n> {outcome.note}" if outcome.note else ""
        return {
            "text": (
                f"{icon} `{outcome.id}` {outcome.upstream}:{outcome.tool} "
                f"requested by {outcome.principal} was {word}{who}{how}.{note}"
            ),
            "event": "approval.decided",
            "request_id": outcome.id,
            "status": outcome.status.value,
            "decided_by": outcome.decided_by,
            "decided_method": outcome.decided_method,
            "tool": f"{outcome.upstream}:{outcome.tool}",
            "call_id": outcome.call_id,
        }

    def post(self, payload: dict[str, Any]) -> bool:
        """Deliver one message. Returns whether it arrived; never raises."""
        if not self.enabled:
            return False
        log = get_logger("gatekeeper.notify")
        try:
            response = httpx.post(self.url.strip(), json=payload, timeout=self.timeout_s)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 — a notification failure is never a call failure
            # The URL is never logged: an incoming-webhook URL is itself the credential.
            log.error(
                "approval notification failed",
                extra={"event": payload.get("event"), "error": type(exc).__name__},
            )
            return False
        log.info("approval notification sent", extra={"event": payload.get("event")})
        return True

    def send(self, payload: dict[str, Any]) -> None:
        """Deliver off the hot path: a slow or dead receiver must not delay a governed call."""
        if not self.enabled:
            return
        try:
            loop = asyncio.get_running_loop()
        except (
            RuntimeError
        ):  # sync context (a test, or the CLI): deliver inline, still never raises
            self.post(payload)
            return
        loop.run_in_executor(None, self.post, payload)


def notifier_from_settings(settings: Any) -> ApprovalNotifier:
    """Build the notifier from ``GATEKEEPER_APPROVAL_WEBHOOK`` / ``GATEKEEPER_DESK_URL``.

    Falls back to the operator alert webhook when no approval-specific one is set, so a small
    deployment that already has one hook does not have to configure a second.
    """
    url = (
        getattr(settings, "approval_webhook", "") or getattr(settings, "alert_webhook", "")
    ).strip()
    return ApprovalNotifier(url=url, desk_url=(getattr(settings, "desk_url", "") or "").strip())
