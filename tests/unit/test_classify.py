"""Unit tests for the config-driven read/write classifier (pure, no I/O)."""

from __future__ import annotations

from gatekeeper.domain.classify import ActionClassifier
from gatekeeper.schemas.enums import ActionKind

PATTERNS = ["create*", "update*", "delete*", "write*", "put*", "exec*", "run*", "send*"]
ANNOTATIONS = {
    "demo-files": {"writes": ["write_file", "delete_file"], "reads": ["read_file", "list_dir"]},
}


def _classifier() -> ActionClassifier:
    return ActionClassifier(name_patterns=PATTERNS, upstream_annotations=ANNOTATIONS)


def test_explicit_write_annotation_wins() -> None:
    assert _classifier().classify("demo-files", "delete_file") is ActionKind.WRITE


def test_explicit_read_annotation_wins_over_pattern() -> None:
    # "read_file" doesn't match a write pattern anyway, but the annotation pins it READ.
    assert _classifier().classify("demo-files", "read_file") is ActionKind.READ


def test_name_pattern_classifies_write_when_unannotated() -> None:
    # An upstream with no annotations falls back to the global write patterns.
    assert _classifier().classify("other", "create_record") is ActionKind.WRITE


def test_unmatched_tool_defaults_to_read() -> None:
    assert _classifier().classify("other", "fetch_status") is ActionKind.READ


def test_annotation_overrides_pattern_collision() -> None:
    # A tool named like a write pattern but annotated as a read -> annotation wins (READ).
    ann = {"svc": {"reads": ["run_report"], "writes": []}}
    clf = ActionClassifier(name_patterns=PATTERNS, upstream_annotations=ann)
    assert clf.classify("svc", "run_report") is ActionKind.READ
