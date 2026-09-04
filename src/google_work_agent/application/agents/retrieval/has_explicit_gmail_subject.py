"""Recognize when a Gmail subject constraint came from the user's words."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

_EXPLICIT_SUBJECT_PATTERN = re.compile(r"(?:제목|subject)(?:이|가|은|는)?\b", re.IGNORECASE)


def has_explicit_gmail_subject(constraints: object) -> bool:
    """Return true only for a subject explicitly scoped by the user request."""

    if not isinstance(constraints, Sequence) or isinstance(constraints, (str, bytes)):
        return False
    has_subject_constraint = any(
        isinstance(item, Mapping)
        and item.get("field") in {"subject", "search_criteria_subject"}
        for item in constraints
    )
    if not has_subject_constraint:
        return False

    original_requests = [
        value
        for item in constraints
        if isinstance(item, Mapping)
        and item.get("kind") == "USER_REQUIREMENT"
        and item.get("field") == "original_search_request"
        for value in _strings(item.get("value"))
    ]
    if not original_requests:
        return True
    return any(_EXPLICIT_SUBJECT_PATTERN.search(request) for request in original_requests)


def _strings(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [item for item in values if isinstance(item, str) and item]


__all__ = ["has_explicit_gmail_subject"]
