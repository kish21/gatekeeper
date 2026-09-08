"""Cedar ``PolicyEngine`` — RBAC policy-as-code (ADR-002).

Implements ``ports.policy.PolicyEngine``. The ONLY layer allowed to import the Cedar SDK
(``cedarpy``) on the policy side (ports & adapters / ADR-004). The authorization contract lives
entirely in ``policies/*.cedar`` (version-controlled config) — **no RBAC rule is hardcoded here**.

Cedar request model (mirrors the policy-file header):
  * **principal** = ``User::"<id>"``  (a member of ``Role::"<role>"`` — the role carries the grants)
  * **action**    = ``Action::"<read|write>"``  (from the call's classified ``action_kind``)
  * **resource**  = ``Tool::"<upstream>::<tool>"``  (with ``upstream``/``tool`` as attributes, so a
    rule can name a whole server without spelling out every tool on it)
  * **context**   = who is calling, and **what the call would actually do**: the arguments, plus
    normalized attributes (``branch``, ``path``, ``table``, ``recipients``, ``domains``,
    ``amount``, …) that mean the same thing across servers. See ``domain.arguments``. This is what
    lets a rule say "not on main", "not the customers table", "not to an external address" instead
    of only "an operator may write". Nothing in the context is persisted.
Default decision is **deny** (Cedar denies anything no ``permit`` matches), so the engine is
fail-closed by construction. It is hardened further:
  * **Fail-loud at load:** an unparseable / missing policy raises ``ConfigError`` so the gateway
    refuses to boot rather than silently authorizing nothing (or everything).
  * **Fail-closed at eval:** ``evaluate`` never raises — any internal error becomes a DENY with a
    reason, honoring the port contract ("on any evaluation error the caller treats it as DENY").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cedarpy import Decision as CedarDecision
from cedarpy import is_authorized, policies_to_json_str

from gatekeeper.config.loader import ConfigError
from gatekeeper.domain.arguments import policy_context
from gatekeeper.infra.logging import get_logger
from gatekeeper.schemas.enums import Verdict
from gatekeeper.schemas.models import Decision, Principal, ToolCall

_log = get_logger("gatekeeper.policy")

#: Cedar entity type names (must match the identifiers used in ``policies/*.cedar``).
_USER, _ROLE, _ACTION, _TOOL = "User", "Role", "Action", "Tool"


def _escape(entity_id: str) -> str:
    """Escape a value for a Cedar entity-id string literal (``Type::"<here>"``).

    The request principal/action/resource must be passed as Cedar EUID *strings*, so an id that
    contains a backslash or double-quote (e.g. an oddly-named upstream tool) would otherwise break
    parsing — or worse, be interpreted as Cedar syntax. Escaping both makes the id inert.
    """
    return entity_id.replace("\\", "\\\\").replace('"', '\\"')


def _euid(entity_type: str, entity_id: str) -> str:
    """Render a Cedar entity UID literal, e.g. ``Tool::"demo::read_file"``."""
    return f'{entity_type}::"{_escape(entity_id)}"'


class CedarPolicyEngine:
    """Evaluate ``policies/*.cedar`` for one ``(principal, call)`` -> allow/deny + reason."""

    def __init__(self, policy_text: str, names: dict[str, str] | None = None) -> None:
        #: Concatenated, already-validated policy source (validated in ``from_config``).
        self._policies = policy_text
        #: Cedar's internal ids ("policy3") -> the `@id("no-writes-to-main")` a human wrote, so a
        #: denial in the ledger names the RULE rather than a position in a file.
        self._names = names or {}

    def _rule_names(self, ids: list[str]) -> str:
        return ", ".join(self._names.get(i, i) for i in ids) or "?"

    @classmethod
    def from_config(cls, policy_dir: Path | str) -> CedarPolicyEngine:
        """Load + validate every ``*.cedar`` file in ``policy_dir``. Fail-loud on a bad policy.

        Raises ``ConfigError`` if the directory is missing, holds no policy, or fails to parse —
        an unauthorizable gateway must not boot silently (a parse error would otherwise deny-all).
        """
        directory = Path(policy_dir)
        if not directory.is_dir():
            raise ConfigError(
                f"Policy dir {directory!s} does not exist. "
                "Set platform.yaml policy.dir to a directory of .cedar files."
            )
        files = sorted(directory.glob("*.cedar"))
        if not files:
            raise ConfigError(
                f"No .cedar policy files found in {directory!s}. The gateway needs an explicit "
                "authorization policy (a missing policy would deny every call)."
            )
        policy_text = "\n".join(path.read_text(encoding="utf-8") for path in files)
        listed = ", ".join(p.name for p in files)
        try:
            # Parse the whole set (raises on bad syntax) AND count the statements parsed.
            parsed = json.loads(policies_to_json_str(policy_text))
            static = parsed.get("staticPolicies", {})
            # Cedar reports which policy decided by position ("policy3"). Every rule that carries
            # an `@id("...")` gets mapped back to that name, so the ledger can say which RULE
            # denied a call instead of where it happened to sit in the file.
            rule_names = {
                key: str((body.get("annotations") or {}).get("id", key))
                for key, body in static.items()
                if isinstance(body, dict)
            }
        except Exception as exc:  # noqa: BLE001 — any parse failure is a boot-blocking misconfig
            raise ConfigError(f"Could not parse Cedar policy ({listed}): {exc}") from exc
        n_policies = len(parsed.get("staticPolicies", {})) + len(parsed.get("templateLinks", []))
        if n_policies == 0:
            # Syntactically valid but EMPTY (e.g. comments only) -> would deny every call silently.
            # The guard exists to make that impossible, so refuse to boot (fail-loud).
            raise ConfigError(
                f"Cedar policy ({listed}) defines no permit/forbid statements — every call would "
                "be denied. Add an explicit policy. Refusing to boot (fail-closed)."
            )
        _log.info(
            "cedar policy loaded",
            extra={"files": [p.name for p in files], "policies": n_policies},
        )
        return cls(policy_text, rule_names)

    def evaluate(self, principal: Principal, call: ToolCall) -> Decision:
        """Decide allow/deny for this call. Never raises — any error is a fail-closed DENY."""
        resource = f"{call.upstream}::{call.tool}"
        action = call.action_kind.value
        try:
            context = self._context(principal, call, action)
            result = is_authorized(
                {
                    "principal": _euid(_USER, principal.id),
                    "action": _euid(_ACTION, action),
                    "resource": _euid(_TOOL, resource),
                    "context": context,
                },
                self._policies,
                self._entities(principal, action, call),
            )
        except Exception as exc:  # noqa: BLE001 — fail-closed: an engine error must not allow
            _log.error(
                "policy evaluation error",
                extra={
                    "call_id": call.call_id,
                    "principal": principal.id,
                    "resource": resource,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return Decision(
                call_id=call.call_id,
                verdict=Verdict.DENY,
                reason=f"policy evaluation error (fail-closed): {type(exc).__name__}",
            )

        if result.decision is CedarDecision.Allow:
            rules = self._rule_names(list(result.diagnostics.reasons))
            return Decision(
                call_id=call.call_id,
                verdict=Verdict.ALLOW,
                reason=(
                    f"allowed by cedar policy [{rules}]: "
                    f"role '{principal.role}' may {action} {resource}"
                ),
            )
        # Deny or NoDecision (e.g. a policy error surfaced at eval) -> fail-closed DENY.
        detail = "; ".join(result.diagnostics.errors)
        forbidding = list(result.diagnostics.reasons)
        if detail:
            suffix = f" (policy errors: {detail})"
        elif forbidding:
            # An explicit `forbid` fired. Naming it is the difference between "computer says no"
            # and an operator knowing which rule to read (or to argue with).
            suffix = f" (forbidden by rule [{self._rule_names(forbidding)}])"
        else:
            suffix = " (default-deny)"
        return Decision(
            call_id=call.call_id,
            verdict=Verdict.DENY,
            reason=(
                f"denied by cedar policy: role '{principal.role}' "
                f"may not {action} {resource}{suffix}"
            ),
        )

    @staticmethod
    def _context(principal: Principal, call: ToolCall, action: str) -> dict[str, Any]:
        """What the rules may know about this request: the caller, the target, the arguments."""
        return {
            "principal": principal.id,
            "role": principal.role,
            "tenant": principal.tenant,
            "action": action,
            "upstream": call.upstream,
            "tool": call.tool,
            **policy_context(call.arguments),
        }

    @staticmethod
    def _entities(principal: Principal, action: str, call: ToolCall) -> list[dict[str, object]]:
        """Build the request's entity store: the User (member of its Role), Role, Action, Tool.

        Membership (``User in Role``) is what lets a role-scoped ``permit`` apply to the caller, so
        the User MUST carry its Role as a parent here for the policy to grant anything. The Tool
        carries its server and tool name as attributes, so a rule can say "anything on the
        production database" without listing every tool that server offers.
        """
        resource = f"{call.upstream}::{call.tool}"
        return [
            {
                "uid": {"type": _USER, "id": principal.id},
                "attrs": {"role": principal.role, "tenant": principal.tenant},
                "parents": [{"type": _ROLE, "id": principal.role}],
            },
            {"uid": {"type": _ROLE, "id": principal.role}, "attrs": {}, "parents": []},
            {"uid": {"type": _ACTION, "id": action}, "attrs": {}, "parents": []},
            {
                "uid": {"type": _TOOL, "id": resource},
                "attrs": {"upstream": call.upstream, "tool": call.tool},
                "parents": [],
            },
        ]


__all__ = ["CedarPolicyEngine"]
