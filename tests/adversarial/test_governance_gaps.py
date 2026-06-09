"""Adversarial — surface M1's governance limitations as ASSERTED facts, not surprises.

A tester's job is to find where governance can be evaded and pin the real behavior, so a limitation
is tracked (and flips the day it's fixed) rather than discovered in production. Two seams, exercised
against the REAL shipped write-detection config + the REAL Cedar policy + a REAL SQLite ledger:

  1. **Classification -> RBAC evasion (HONEST LIMITATION).** Authorization keys off the *classified*
     ``action_kind``. The M1 classifier is name-pattern + annotation based (``ActionClassifier``),
     so a destructive tool whose name matches no ``write_detection.name_pattern`` AND carries no
     explicit ``writes:`` annotation is classified **read** — and a ``readonly`` role is therefore
     ALLOWED to call it. This is the documented best-effort nature of static classification; the LLM
     risk classifier in M2 (ADR-005, fails closed to human approval) is the planned backstop. The
     lever that exists TODAY is an explicit annotation in ``upstreams.yaml`` — proven to close it.

  2. **Read access-scoping.** ``read(principal=...)`` enforces within-tenant owner isolation (one
     principal cannot list another's entries); ``get(call_id)`` is deliberately NOT principal-scoped
     (documented limitation — safe today: single tenant + unguessable UUID4 call_ids).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from gatekeeper.adapters.ledger.sqlite import SqliteLedgerStore
from gatekeeper.adapters.policy.cedar import CedarPolicyEngine
from gatekeeper.config.loader import load_config
from gatekeeper.db.base import Base
from gatekeeper.domain.classify import ActionClassifier
from gatekeeper.domain.errors import IdentityError, PolicyDenied
from gatekeeper.gateway.factory import _build_classifier
from gatekeeper.gateway.pipeline import GatewayPipeline
from gatekeeper.schemas.enums import ActionKind, Verdict
from gatekeeper.schemas.ledger import LedgerEntry
from gatekeeper.schemas.models import Principal, ToolCall, ToolResult

KEY = "k" * 64

# A destructive tool whose name matches NONE of the shipped write_detection patterns
# (create*/update*/delete*/write*/put*/exec*/run*/send*) — so static classification calls it a read.
EVASIVE_DESTRUCTIVE_TOOL = "drop_table"


class _FakeIdentity:
    """Minimal IdentityResolver: isolates the variable under test (classification), not auth."""

    def __init__(self, mapping: dict[str, Principal]) -> None:
        self._m = mapping

    def resolve(self, token: str) -> Principal:
        principal = self._m.get(token)
        if principal is None:
            raise IdentityError("unknown token")
        return principal


class _SpyUpstream:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def forward(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        return ToolResult(call_id=call.call_id, ok=True, summary="forwarded")


@pytest.fixture
def store(tmp_path: Any) -> Iterator[SqliteLedgerStore]:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield SqliteLedgerStore(session, KEY)
    session.close()


def _pipeline(
    store: SqliteLedgerStore, upstream: Any, classifier: ActionClassifier
) -> GatewayPipeline:
    # REAL Cedar policy + REAL ledger; identity and the tool index are the only fakes, so the
    # classification->RBAC seam is exercised exactly as in production.
    return GatewayPipeline(
        identity=_FakeIdentity({"ro": Principal(id="bob", role="readonly")}),
        classifier=classifier,
        policy=CedarPolicyEngine.from_config("policies"),
        ledger=store,
        upstream=upstream,
        hmac_key=KEY,
    )


def _real_classifier(
    extra_annotations: dict[str, dict[str, list[str]]] | None = None,
) -> ActionClassifier:
    """The production classifier, built from the SHIPPED config (no hardcoded patterns)."""
    config = load_config()
    classifier = _build_classifier(config["product"], config["upstreams"])
    if not extra_annotations:
        return classifier
    # Rebuild with an added/overridden upstream annotation (the operator's mitigation lever).
    merged = dict(classifier._annotations)
    merged.update(extra_annotations)
    return ActionClassifier(
        name_patterns=list(classifier._name_patterns),
        upstream_annotations=merged,
    )


# --- 1. Classification -> RBAC evasion -------------------------------------------------------


def test_real_config_classifies_an_evasive_destructive_tool_as_read() -> None:
    # Ground the limitation at the unit level against the REAL shipped patterns: a destructive verb
    # the pattern list doesn't anticipate (drop/purge/truncate/remove...) defaults to READ.
    classifier = _real_classifier()
    assert classifier.classify("demo-files", EVASIVE_DESTRUCTIVE_TOOL) is ActionKind.READ


async def test_unannotated_destructive_tool_slips_past_readonly_rbac(
    store: SqliteLedgerStore,
) -> None:
    """HONEST LIMITATION (pinned): readonly reaches an unannotated destructive tool.

    Because ``drop_table`` is classified READ, the shipped ``readonly`` permit (action == read)
    grants it — the call is ALLOWED and forwarded. The call is still fully authenticated and
    recorded in the tamper-evident ledger (no call slips past *audit*); what slips is the
    *write-intent gate*. When M2's LLM risk classifier lands, this test should flip to a deny —
    that's the regression signal.
    """
    spy = _SpyUpstream()
    pipe = _pipeline(store, spy, _real_classifier())

    result = await pipe.handle(
        token="ro",
        upstream="demo-files",
        tool=EVASIVE_DESTRUCTIVE_TOOL,
        arguments={"table": "users"},
        call_id="gap1",
    )

    # The documented gap: a destructive call by readonly was allowed through (classified read).
    assert result.ok and len(spy.calls) == 1
    recorded = store.read(limit=10)
    assert all(e.verdict is Verdict.ALLOW for e in recorded)
    # ...but it is NOT ungoverned: it was authenticated, classified, and provably audited.
    assert recorded[-1].action_kind is ActionKind.READ
    assert recorded[-1].principal == "bob"
    assert store.verify().ok


async def test_annotating_the_destructive_tool_closes_the_gap(store: SqliteLedgerStore) -> None:
    """The mitigation that exists TODAY: annotate the tool as a write in upstreams.yaml.

    With ``drop_table`` declared a write, the classifier returns WRITE, the readonly permit no
    longer matches, and the same call is denied + recorded + never forwarded — proving the gap is a
    *config* gap (an un-annotated tool), not a hole in the enforcement path itself.
    """
    spy = _SpyUpstream()
    classifier = _real_classifier(
        {"demo-files": {"writes": [EVASIVE_DESTRUCTIVE_TOOL], "reads": []}}
    )
    pipe = _pipeline(store, spy, classifier)

    with pytest.raises(PolicyDenied, match="readonly"):
        await pipe.handle(
            token="ro",
            upstream="demo-files",
            tool=EVASIVE_DESTRUCTIVE_TOOL,
            arguments={"table": "users"},
            call_id="gap2",
        )

    assert spy.calls == []  # the destructive write never reached the upstream
    recorded = store.read(limit=10)
    assert len(recorded) == 1 and recorded[0].verdict is Verdict.DENY
    assert recorded[0].action_kind is ActionKind.WRITE
    assert store.verify().ok


# --- 2. Read access-scoping ------------------------------------------------------------------


def _seed(store: SqliteLedgerStore, principal: str, call_id: str) -> None:
    store.append(
        LedgerEntry(
            call_id=call_id,
            ts="2026-06-09T12:00:00+00:00",
            tenant="default",
            principal=principal,
            role="readonly",
            upstream="demo-files",
            tool="read_file",
            action_kind=ActionKind.READ,
            verdict=Verdict.ALLOW,
            reason="ok",
            payload_hash="0" * 64,
            result_summary="ok",
        )
    )


def test_read_is_scoped_by_principal(store: SqliteLedgerStore) -> None:
    # Within-tenant owner isolation: bob must not see alice's entries via a principal-scoped read.
    _seed(store, "alice", "a1")
    _seed(store, "bob", "b1")
    _seed(store, "alice", "a2")

    bob_view = store.read(principal="bob")
    assert {e.call_id for e in bob_view} == {"b1"}
    assert all(e.principal == "bob" for e in bob_view)

    alice_view = store.read(principal="alice")
    assert {e.call_id for e in alice_view} == {"a1", "a2"}


def test_get_is_not_principal_scoped_known_limitation(store: SqliteLedgerStore) -> None:
    """Pinned limitation: ``get(call_id)`` is NOT principal/tenant-scoped (see PRODUCT.md#Tests).

    Anyone holding a ``call_id`` retrieves that decision regardless of owner. Safe today (single
    tenant + unguessable UUID4 call_ids); the test exists so the day multi-tenant lands, this is a
    known box to tighten (the deferred multi-tenant trigger in #Scope), not a forgotten one.
    """
    _seed(store, "alice", "a1")
    entry = store.get("a1")  # retrieved without supplying a principal
    assert entry is not None and entry.principal == "alice"
