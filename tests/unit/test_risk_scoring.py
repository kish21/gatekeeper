"""Unit — scoring a write, so a person's attention goes where it changes the outcome.

Holding every write is safe and unsustainable: forty approvals a day makes a rubber stamp of the
one that mattered. These tests pin down what the score is allowed to do (decide how much attention
a write gets) and what it must never do (decide whether a call is permitted — the rulebook does
that, and an unscored write is still held).

The shipped ``config/product.yaml`` signals are tested against real-looking calls, so the file an
operator will edit is a tested artifact rather than an illustration.
"""

from __future__ import annotations

import pytest

from gatekeeper.config.loader import load_config
from gatekeeper.domain.arguments import policy_context
from gatekeeper.domain.risk import RiskScorer, RiskSignal, hold_threshold
from gatekeeper.gateway.pipeline import ApprovalPolicy
from gatekeeper.schemas.enums import ActionKind


@pytest.fixture(scope="module")
def shipped() -> RiskScorer:
    return RiskScorer.from_config(load_config()["product"])


# --- the shipped signals, against calls that look like real work --------------------------------


@pytest.mark.parametrize(
    ("target", "arguments", "expected_signal"),
    [
        ("mail:send_email", {"to": "me@gmail.com"}, "recipient-outside-the-company"),
        ("sharepoint:upload", {"path": "/prod/secrets/k.txt"}, "secrets-path"),
        ("finance:transfer", {"amount": 25000}, "large-amount"),
        ("database:update_row", {"table": "customers"}, "customer-or-payment-data"),
        ("github:push", {"branch": "main"}, "production-branch"),
        ("database:run", {"sql": "delete from orders"}, "destructive-wording"),
    ],
)
def test_a_risky_write_scores_above_an_ordinary_one(
    shipped: RiskScorer, target: str, arguments: dict[str, object], expected_signal: str
) -> None:
    risky = shipped.score(target, policy_context(arguments))
    ordinary = shipped.score("jira:createJiraIssue", policy_context({"summary": "Look into this"}))

    assert expected_signal in risky.reason
    assert risky.risk > ordinary.risk
    assert risky.risk >= 0.5, "a signal must lift a write above a sensible working threshold"


def test_ordinary_work_is_not_dressed_up_as_risky(shipped: RiskScorer) -> None:
    """If everything scores high, the score is noise and the desk is a queue again."""
    for target, arguments in [
        ("jira:createJiraIssue", {"summary": "Investigate the billing job"}),
        ("mail:send_email", {"to": "sam@corp.example", "body": "notes"}),
        ("github:create_issue", {"title": "flaky test", "branch": "feature/x"}),
    ]:
        assessment = shipped.score(target, policy_context(arguments))
        assert assessment.risk < 0.5, f"{target} should be ordinary, scored {assessment.risk}"


def test_some_tools_always_stop_whatever_they_score(shipped: RiskScorer) -> None:
    assessment = shipped.score("github:merge_pull_request", policy_context({"pull_number": 7}))
    assert assessment.risk == 1.0
    assert "always held" in assessment.reason


def test_the_shipped_default_holds_every_write() -> None:
    """Ship safe: a gateway nobody has tuned must not be quietly letting writes through."""
    assert hold_threshold(load_config()["product"]) == 0.0


# --- the scorer's own behaviour ------------------------------------------------------------------


def test_signals_add_up_and_are_capped() -> None:
    scorer = RiskScorer(
        base=0.3,
        signals=(
            RiskSignal(id="a", weight=0.4, attribute="branch", equals=("main",)),
            RiskSignal(id="b", weight=0.5, text=("drop ",)),
        ),
    )
    both = scorer.score("db:run", policy_context({"branch": "main", "sql": "drop table x"}))
    assert both.risk == 1.0  # 0.3 + 0.4 + 0.5, capped
    assert both.reason == "a, b"


def test_an_unmatched_attribute_contributes_nothing() -> None:
    scorer = RiskScorer(
        signals=(RiskSignal(id="a", weight=0.5, attribute="branch", equals=("main",)),)
    )
    assert scorer.score("x:y", policy_context({"branch": "feature"})).risk == 0.3
    assert scorer.score("x:y", policy_context({})).risk == 0.3


def test_outside_matches_a_value_that_is_not_ours() -> None:
    signal = RiskSignal(id="ext", weight=0.4, attribute="domains", outside=("corp.example",))
    assert signal.matches(policy_context({"to": "a@corp.example"})) is False
    assert signal.matches(policy_context({"to": "a@corp.example, b@gmail.com"})) is True


def test_never_hold_is_honoured_and_visible() -> None:
    """A hole in the gate is allowed, but it says so in the record."""
    scorer = RiskScorer(never_hold=frozenset({"demo:read_ish_write"}))
    assessment = scorer.score("demo:read_ish_write", policy_context({}))
    assert assessment.risk == 0.0
    assert "never held" in assessment.reason


# --- what the score is allowed to decide ---------------------------------------------------------


def test_a_score_below_the_threshold_lets_the_write_through() -> None:
    policy = ApprovalPolicy(writes_require=True, hold_at=0.5)
    assert policy.applies("operator", ActionKind.WRITE, risk=0.3) is False
    assert policy.applies("operator", ActionKind.WRITE, risk=0.5) is True
    assert policy.applies("operator", ActionKind.WRITE, risk=0.9) is True


def test_an_unscored_write_is_still_held() -> None:
    """Absence of a score is never a reason to skip the human."""
    assert (
        ApprovalPolicy(writes_require=True, hold_at=0.5).applies(
            "operator", ActionKind.WRITE, risk=None
        )
        is True
    )


def test_reads_are_never_held_and_exempt_roles_still_pass() -> None:
    policy = ApprovalPolicy(writes_require=True, hold_at=0.0, exempt_roles=frozenset({"admin"}))
    assert policy.applies("operator", ActionKind.READ, risk=1.0) is False
    assert policy.applies("admin", ActionKind.WRITE, risk=1.0) is False
