"""Aggregate already-produced Review findings without performing a new LLM call."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def aggregate_review_findings(findings: Iterable[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    """Stable-deduplicate findings while preserving their owning dimension metadata."""
    result: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for finding in findings:
        item = dict(finding)
        code = item.get("code")
        description = item.get("description")
        if not isinstance(code, str) or not code:
            raise ValueError("review finding code is required")
        if not isinstance(description, str):
            raise ValueError("review finding description must be a string")
        identity = (
            code,
            description,
            item.get("action_id"),
            item.get("route_id"),
            tuple(item.get("required_information", ())) if isinstance(item.get("required_information"), list) else None,
        )
        if identity not in seen:
            seen.add(identity)
            result.append(item)
    return tuple(result)
