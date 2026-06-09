"""Config-driven read/write classification — NOT hardcoded.

A call's ``action_kind`` enriches the audit record now and gates LLM risk-scoring + approval in M2.
The rule is data, sourced from config (PRODUCT.md#Contracts):
  1. an explicit per-upstream annotation (``upstreams.yaml`` writes/reads) WINS, then
  2. a glob over ``product.yaml`` ``write_detection.name_patterns`` (e.g. ``delete*`` -> write).
A tool matching neither defaults to READ (the non-mutating, lower-risk assumption); annotate writes
explicitly to be sure they are gated in M2.

Pure functions — no I/O, no SDK — so classification is fully unit-testable in isolation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fnmatch import fnmatch

from gatekeeper.schemas.enums import ActionKind


class ActionClassifier:
    """Decide read vs write for ``(upstream, tool)`` from config. Annotation beats name pattern."""

    def __init__(
        self,
        *,
        name_patterns: Sequence[str],
        upstream_annotations: Mapping[str, Mapping[str, Sequence[str]]],
    ) -> None:
        self._name_patterns = tuple(name_patterns)
        # {upstream_name: {"writes": [...], "reads": [...]}}
        self._annotations = upstream_annotations

    def classify(self, upstream: str, tool: str) -> ActionKind:
        ann = self._annotations.get(upstream, {})
        if tool in (ann.get("writes") or ()):
            return ActionKind.WRITE
        if tool in (ann.get("reads") or ()):
            return ActionKind.READ
        if any(fnmatch(tool, pattern) for pattern in self._name_patterns):
            return ActionKind.WRITE
        return ActionKind.READ
