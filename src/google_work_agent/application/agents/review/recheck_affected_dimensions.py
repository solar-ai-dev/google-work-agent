"""Select only Review dimensions affected by a prior finding set."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def recheck_affected_dimensions(
    findings: Iterable[Mapping[str, object]],
    *,
    affected_action_ids: Iterable[str] = (),
    affected_route_ids: Iterable[str] = (),
) -> tuple[dict[str, object], ...]:
    """Bound recheck scope; this function does not create a new PromptRef or LLM topology."""
    action_ids = set(affected_action_ids)
    route_ids = set(affected_route_ids)
    if not action_ids and not route_ids:
        return tuple(dict(item) for item in findings)
    result: list[dict[str, object]] = []
    for finding in findings:
        action_id = finding.get("action_id")
        route_id = finding.get("route_id")
        if action_id is None and route_id is None:
            result.append(dict(finding))
        elif isinstance(action_id, str) and action_id in action_ids:
            result.append(dict(finding))
        elif isinstance(route_id, str) and route_id in route_ids:
            result.append(dict(finding))
    return tuple(result)
