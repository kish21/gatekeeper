"""What the policy is allowed to know about a call's arguments — pure, bounded, no I/O.

Until now a rule could say "an operator may write to github", but not "…except on `main`". Every
control an enterprise actually has is about the object, not the verb: not production, not the
customers table, not an external recipient, not over ten thousand. That needs the arguments in
front of the policy engine.

Two problems come with that, and this module exists to solve both.

**Shape.** Tool servers name the same thing differently — ``branch``, ``ref``, ``head``; ``path``,
``file``, ``filename``; ``to``, ``recipient``, ``recipients``. A rule written against one server's
spelling would silently not apply to another's. So the raw arguments are passed through *and*
normalized into a small set of named attributes a rule can rely on across servers.

**Blast radius.** Arguments can be enormous, deeply nested, or hostile. The context handed to the
policy engine is therefore bounded on every axis — depth, key count, string length, list length —
and holds only scalars. Nothing here is persisted: the ledger keeps the keyed payload hash, as
always. This is what the policy *sees*, for the microsecond it takes to decide.
"""

from __future__ import annotations

import re
from typing import Any

#: Bounds on the context. A pathological argument set costs a bounded amount of work and can never
#: turn into a policy-evaluation failure (which would fail the call closed).
MAX_KEYS = 40
MAX_STRING = 512
MAX_LIST = 20
#: Longest joined text a rule can pattern-match with `like`. Generous, but finite.
MAX_TEXT = 4000

#: Argument names that mean the same thing across servers -> the attribute a rule can rely on.
#: Order matters inside each tuple: the first name present wins, so the most specific spelling of
#: a concept beats a generic one.
_ALIASES: dict[str, tuple[str, ...]] = {
    "branch": ("branch", "branch_name", "ref", "head", "base", "target_branch"),
    "path": ("path", "file_path", "filepath", "file", "filename", "key", "document_path"),
    "repo": ("repo", "repository", "repo_name", "project", "project_key"),
    "table": ("table", "table_name", "collection", "dataset", "index"),
    "statement": ("query", "sql", "statement", "command", "script", "jql", "expression"),
    "recipients": ("to", "recipient", "recipients", "email", "cc", "bcc", "address"),
    "amount": ("amount", "total", "value", "price", "quantity", "limit"),
    "site": ("site", "site_url", "host", "url", "endpoint", "server"),
    "identifier": ("id", "issue_key", "issue_id", "pull_number", "number", "ticket", "item_id"),
}

#: Split a recipient list written as one string ("a@x.com, b@y.com; c@z.com").
_RECIPIENT_SPLIT = re.compile(r"[,;\s]+")


def _scalar(value: Any) -> Any | None:
    """One argument value, bounded, or ``None`` if the policy has no business seeing it."""
    if isinstance(value, bool):  # before int: bool IS an int in Python, and rules mean the boolean
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        return value[:MAX_STRING]
    return None


def flatten(arguments: dict[str, Any], *, prefix: str = "", depth: int = 0) -> dict[str, Any]:
    """Arguments as a flat, bounded map of scalars: ``{"issue.fields.summary": "..."}``.

    Nesting is flattened with dots so a rule can reach a field without the engine needing nested
    records, and lists of scalars survive as lists (a rule wants ``contains``). Two levels deep is
    enough for every real MCP tool schema seen so far; deeper structures are dropped rather than
    walked forever.
    """
    flat: dict[str, Any] = {}
    if depth > 2:
        return flat
    for raw_key, value in arguments.items():
        if len(flat) >= MAX_KEYS:
            break
        key = f"{prefix}{raw_key}"
        scalar = _scalar(value)
        if scalar is not None:
            flat[key] = scalar
        elif isinstance(value, dict):
            flat.update(flatten(value, prefix=f"{key}.", depth=depth + 1))
        elif isinstance(value, list):
            items = [s for s in (_scalar(v) for v in value[:MAX_LIST]) if s is not None]
            if items:
                flat[key] = [str(i) for i in items]
    return dict(list(flat.items())[:MAX_KEYS])


def _first_alias(flat: dict[str, Any], names: tuple[str, ...]) -> Any | None:
    """The value of the first of ``names`` present, matching either ``to`` or ``issue.to``."""
    for name in names:
        if name in flat:
            return flat[name]
        for key, value in flat.items():
            if key.rsplit(".", 1)[-1] == name:
                return value
    return None


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return [part for part in _RECIPIENT_SPLIT.split(str(value)) if part]


def _domains(recipients: list[str]) -> list[str]:
    """The mail domains a call would send to — the attribute an exfiltration rule needs."""
    return sorted({r.rsplit("@", 1)[-1].lower() for r in recipients if "@" in r})


def derive(flat: dict[str, Any]) -> dict[str, Any]:
    """The normalized attributes: the same concept under one name, whatever the server calls it."""
    derived: dict[str, Any] = {}
    for attribute, names in _ALIASES.items():
        value = _first_alias(flat, names)
        if value is None:
            continue
        if attribute == "recipients":
            recipients = _as_list(value)
            derived["recipients"] = recipients[:MAX_LIST]
            if domains := _domains(recipients):
                derived["domains"] = domains
        elif attribute == "amount":
            if isinstance(value, int | float) and not isinstance(value, bool):
                derived["amount"] = value
        else:
            derived[attribute] = str(value)[:MAX_STRING]
    return derived


def searchable_text(flat: dict[str, Any]) -> str:
    """Every string in the arguments, lowercased and joined — for `like` pattern rules.

    A rule that has to catch ``DROP TABLE`` wherever it appears (in ``sql``, in ``command``, in a
    field nobody anticipated) matches against this instead of guessing the key.
    """
    parts: list[str] = []
    for value in flat.values():
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(v) for v in value)
    return " ".join(parts).lower()[:MAX_TEXT]


def policy_context(arguments: dict[str, Any]) -> dict[str, Any]:
    """Everything a rule may know about this call's arguments, bounded and normalized.

    Returns ``{"args": {...}, "arg_keys": [...], "arg_text": "...", <derived attributes>}``.
    ``arg_keys`` is there so a rule can require a field to be *present* ("a transfer must name an
    account"), which is a different question from what its value is.
    """
    flat = flatten(arguments)
    context: dict[str, Any] = {
        "args": flat,
        "arg_keys": sorted(flat),
        "arg_text": searchable_text(flat),
    }
    context.update(derive(flat))
    return context
