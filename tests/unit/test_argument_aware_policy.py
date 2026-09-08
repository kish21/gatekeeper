"""Unit — rules that read the ARGUMENTS, not just the verb.

"An operator may write to github" and "an operator may delete the main branch" used to be the same
sentence to this gateway. They are not the same sentence to anybody who has to sign off on it.

Two things are tested here. First the extraction (``domain.arguments``): different servers spell
the same concept differently, arguments can be nested, enormous, or hostile, and none of that may
reach the policy engine unbounded. Then the rules themselves, against the policy this repository
actually ships — so the file in ``policies/`` is a tested artifact, not an illustration.
"""

from __future__ import annotations

from typing import Any

import pytest

from gatekeeper.adapters.policy.cedar import CedarPolicyEngine
from gatekeeper.domain.arguments import MAX_KEYS, MAX_STRING, policy_context
from gatekeeper.schemas.enums import ActionKind, Verdict
from gatekeeper.schemas.models import Principal, ToolCall

# --- what the policy is allowed to see ---------------------------------------------------------


@pytest.mark.parametrize(
    ("arguments", "attribute", "expected"),
    [
        # The same concept, as five different servers spell it.
        ({"branch": "main"}, "branch", "main"),
        ({"ref": "release/2.1"}, "branch", "release/2.1"),
        ({"file_path": "/etc/hosts"}, "path", "/etc/hosts"),
        ({"filename": "report.xlsx"}, "path", "report.xlsx"),
        ({"table_name": "customers"}, "table", "customers"),
        ({"sql": "select 1"}, "statement", "select 1"),
        ({"jql": "project = OPS"}, "statement", "project = OPS"),
        ({"repository": "acme/api"}, "repo", "acme/api"),
        ({"amount": 25000}, "amount", 25000),
        # Nested one level down, where a real MCP tool schema puts it.
        ({"issue": {"fields": {"project_key": "OPS"}}}, "repo", "OPS"),
    ],
)
def test_the_same_concept_is_named_the_same_way(
    arguments: dict[str, Any], attribute: str, expected: object
) -> None:
    """A rule written once applies to every server that means the same thing."""
    assert policy_context(arguments)[attribute] == expected


def test_recipients_and_their_domains_are_derived() -> None:
    """The attribute an exfiltration rule needs, from however the server takes addresses."""
    context = policy_context({"to": "a@corp.example, b@gmail.com"})
    assert context["recipients"] == ["a@corp.example", "b@gmail.com"]
    assert context["domains"] == ["corp.example", "gmail.com"]


def test_arguments_are_flattened_and_listed() -> None:
    context = policy_context({"issue": {"fields": {"summary": "Broken"}}, "notify": True})
    assert context["args"]["issue.fields.summary"] == "Broken"
    assert context["args"]["notify"] is True
    # `arg_keys` lets a rule require that a field was SUPPLIED, which is a different question.
    assert context["arg_keys"] == ["issue.fields.summary", "notify"]


def test_every_string_is_searchable_lowercased() -> None:
    """So a rule can catch `DROP TABLE` wherever the server decided to put it."""
    assert "drop table x" in policy_context({"anything": "DROP TABLE x"})["arg_text"]


def test_the_context_is_bounded_on_every_axis() -> None:
    """A hostile or merely huge argument set costs a bounded amount of work.

    An unbounded context would be a denial-of-service on the policy engine — and since an
    evaluation error is a fail-closed DENY, that is an outage, not just a slow call.
    """
    context = policy_context(
        {
            **{f"k{i}": f"v{i}" for i in range(200)},
            "huge": "x" * 10_000,
            "deep": {"a": {"b": {"c": {"d": "too far"}}}},
            "listy": list(range(100)),
        }
    )
    assert len(context["args"]) <= MAX_KEYS
    assert all(len(str(v)) <= MAX_STRING for v in context["args"].values() if isinstance(v, str))
    assert "deep.a.b.c.d" not in context["args"]


def test_values_the_policy_has_no_use_for_are_dropped() -> None:
    context = policy_context({"ok": "yes", "blob": b"\x00\x01", "none": None})
    assert set(context["args"]) == {"ok"}


# --- the rules this repository ships ------------------------------------------------------------


@pytest.fixture(scope="module")
def policy() -> CedarPolicyEngine:
    """The real policies/ directory. These tests fail if someone weakens the shipped rules."""
    return CedarPolicyEngine.from_config("policies")


def _decide(
    policy: CedarPolicyEngine,
    role: str,
    upstream: str,
    tool: str,
    arguments: dict[str, Any],
    kind: ActionKind = ActionKind.WRITE,
) -> tuple[Verdict, str]:
    decision = policy.evaluate(
        Principal(id="alice" if role != "admin" else "root", role=role),
        ToolCall(call_id="c1", upstream=upstream, tool=tool, arguments=arguments, action_kind=kind),
    )
    return decision.verdict, decision.reason


def test_the_same_tool_is_allowed_or_denied_by_its_arguments(policy: CedarPolicyEngine) -> None:
    """The whole point: one tool, one role, two different answers."""
    denied, reason = _decide(policy, "operator", "github", "delete_branch", {"branch": "main"})
    allowed, _ = _decide(policy, "operator", "github", "delete_branch", {"branch": "feature/x"})

    assert denied is Verdict.DENY
    assert allowed is Verdict.ALLOW
    # The ledger names the rule, so an operator knows which one to read — or to argue with.
    assert "no-writes-to-the-default-branch" in reason


def test_a_guardrail_stops_an_admin_too(policy: CedarPolicyEngine) -> None:
    """A forbid beats every permit. Without this, "guardrail" means "suggestion"."""
    verdict, reason = _decide(policy, "admin", "github", "delete_branch", {"branch": "main"})
    assert verdict is Verdict.DENY
    assert "no-writes-to-the-default-branch" in reason


@pytest.mark.parametrize(
    "statement",
    ["DROP TABLE customers", "truncate orders", "delete from invoices where 1=1"],
)
def test_destructive_sql_is_refused_wherever_it_hides(
    policy: CedarPolicyEngine, statement: str
) -> None:
    verdict, reason = _decide(policy, "operator", "database", "execute", {"command": statement})
    assert verdict is Verdict.DENY
    assert "no-destructive-sql" in reason


def test_ordinary_sql_still_passes(policy: CedarPolicyEngine) -> None:
    verdict, _ = _decide(
        policy, "operator", "database", "execute", {"sql": "update orders set paid = true"}
    )
    assert verdict is Verdict.ALLOW


def test_mail_to_a_colleague_passes_and_mail_outside_does_not(policy: CedarPolicyEngine) -> None:
    inside, _ = _decide(policy, "operator", "mail", "send_email", {"to": "sam@corp.example"})
    outside, reason = _decide(policy, "operator", "mail", "send_email", {"to": "me@gmail.com"})

    assert inside is Verdict.ALLOW
    assert outside is Verdict.DENY
    assert "no-mail-to-outside-addresses" in reason


def test_secrets_are_readable_but_not_writable(policy: CedarPolicyEngine) -> None:
    read, _ = _decide(
        policy, "operator", "sharepoint", "read", {"path": "/prod/secrets/x"}, ActionKind.READ
    )
    write, reason = _decide(policy, "operator", "sharepoint", "upload", {"path": "/prod/secrets/x"})
    assert read is Verdict.ALLOW
    assert write is Verdict.DENY
    assert "no-writes-to-secrets" in reason


def test_customer_data_is_not_edited_by_an_assistant(policy: CedarPolicyEngine) -> None:
    verdict, reason = _decide(
        policy, "operator", "database", "update_row", {"table": "customers", "id": 4}
    )
    assert verdict is Verdict.DENY
    assert "no-writes-to-customer-data" in reason


def test_role_rules_still_hold(policy: CedarPolicyEngine) -> None:
    """Arguments ADD precision; they do not weaken the role check that was there before."""
    verdict, _ = _decide(policy, "readonly", "demo-files", "write_file", {"path": "notes.txt"})
    assert verdict is Verdict.DENY


def test_an_unparseable_argument_never_becomes_an_allow(policy: CedarPolicyEngine) -> None:
    """Fail-closed: whatever arrives in the arguments, the answer is a decision, never a crash."""
    verdict, _ = _decide(
        policy,
        "readonly",
        "database",
        "execute",
        {"weird": {"deeply": {"nested": {"beyond": {"limits": object()}}}}, "n": float("inf")},
    )
    assert verdict is Verdict.DENY
