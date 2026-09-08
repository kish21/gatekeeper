"""How risky is this write? — a declarative score, no I/O, no model call.

Holding *every* write for a person is the right default and the wrong steady state. Forty
approvals a day turns a careful reviewer into a clicking machine, and the one that mattered goes
through with the rest. Attention is the scarce resource this product spends, so it has to be spent
where it changes the outcome.

So a write is scored, and only a score at or above the threshold stops at the desk. The signals
that make a call risky are **configuration, not code** (``product.yaml`` ``risk``) for the same
reason the policy is: what counts as risky differs per company, changes over time, and has to be
readable by the person who will be woken up by it.

Two decisions worth stating plainly:

* **This is deterministic, not an LLM.** A score that cannot be reproduced cannot be argued with
  in an audit, and a scorer that needs a network call sits in a fail-closed path where an outage
  would mean denying every write. The seam for a model-based classifier is
  ``ports.risk``-shaped — a scorer is just something with ``score()`` — but the shipped one is
  arithmetic over attributes you can read.
* **It never overrides the policy.** A call the rulebook denies is denied whatever it scores; a
  call the rulebook allows is *held or not held*. Risk decides how much human attention a write
  gets, never whether it is permitted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gatekeeper.schemas.models import RiskAssessment

#: A write with no matching signal still carries this much risk: it is a change to a real system.
DEFAULT_BASE = 0.3
#: Hold everything at or above this. 0.0 means "hold every write" — the safe default.
DEFAULT_HOLD_AT = 0.0


@dataclass(frozen=True)
class RiskSignal:
    """One reason a write might deserve a person's attention, and how much it adds.

    Exactly one matcher applies, tried in the order below:

    ``equals``     the named attribute is one of these values ("branch is main")
    ``text``       any of these strings appears anywhere in the call ("drop table")
    ``at_least``   the named numeric attribute reaches this ("amount over 10000")
    ``outside``    the named attribute has a value NOT in this list ("a recipient we do not own")
    ``present``    the named attribute exists at all ("this call names a customer")
    """

    id: str
    weight: float
    attribute: str = ""
    equals: tuple[str, ...] = ()
    text: tuple[str, ...] = ()
    at_least: float | None = None
    outside: tuple[str, ...] = ()
    present: bool = False

    def matches(self, context: dict[str, Any]) -> bool:
        if self.text:
            haystack = str(context.get("arg_text", ""))
            return any(needle.lower() in haystack for needle in self.text)
        value = context.get(self.attribute)
        if value is None:
            return False
        if self.equals:
            return any(str(v).lower() in self.equals for v in _as_values(value))
        if self.at_least is not None:
            return isinstance(value, int | float) and float(value) >= self.at_least
        if self.outside:
            return any(str(v).lower() not in self.outside for v in _as_values(value))
        return self.present

    @classmethod
    def from_config(cls, raw: dict[str, Any]) -> RiskSignal:
        return cls(
            id=str(raw.get("id", "unnamed")),
            weight=float(raw.get("weight", 0.0)),
            attribute=str(raw.get("attribute", "")),
            equals=tuple(str(v).lower() for v in raw.get("equals", []) or []),
            text=tuple(str(v).lower() for v in raw.get("text", []) or []),
            at_least=float(raw["at_least"]) if raw.get("at_least") is not None else None,
            outside=tuple(str(v).lower() for v in raw.get("outside", []) or []),
            present=bool(raw.get("present", False)),
        )


def _as_values(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else [value]


@dataclass(frozen=True)
class RiskScorer:
    """Score a write from the same attributes the policy sees. Pure, and cheap enough to be free."""

    base: float = DEFAULT_BASE
    signals: tuple[RiskSignal, ...] = ()
    #: Tools that always stop at the desk whatever they score — the handful nobody wants automated.
    always_hold: frozenset[str] = field(default_factory=frozenset)
    #: Tools that never stop, however they score. Use sparingly; it is a hole in the gate by choice.
    never_hold: frozenset[str] = field(default_factory=frozenset)

    def score(self, target: str, context: dict[str, Any]) -> RiskAssessment:
        """Rate one write. ``target`` is ``upstream:tool``; ``context`` is the policy context."""
        if target in self.never_hold:
            return RiskAssessment(risk=0.0, is_write=True, reason=f"{target} is never held")
        if target in self.always_hold:
            return RiskAssessment(risk=1.0, is_write=True, reason=f"{target} is always held")

        fired = [s for s in self.signals if s.matches(context)]
        risk = min(1.0, self.base + sum(s.weight for s in fired))
        reason = ", ".join(s.id for s in fired) if fired else "no risk signals"
        return RiskAssessment(risk=round(risk, 3), is_write=True, reason=reason)

    @classmethod
    def from_config(cls, product: dict[str, Any]) -> RiskScorer:
        raw = product.get("risk") or {}
        return cls(
            base=float(raw.get("base", DEFAULT_BASE)),
            signals=tuple(RiskSignal.from_config(s) for s in raw.get("signals", []) or []),
            always_hold=frozenset(str(t) for t in raw.get("always_hold", []) or []),
            never_hold=frozenset(str(t) for t in raw.get("never_hold", []) or []),
        )


def hold_threshold(product: dict[str, Any]) -> float:
    """The score at which a write stops at the desk. Absent = hold every write (fail-safe)."""
    raw = product.get("risk") or {}
    return float(raw.get("hold_at", DEFAULT_HOLD_AT))
