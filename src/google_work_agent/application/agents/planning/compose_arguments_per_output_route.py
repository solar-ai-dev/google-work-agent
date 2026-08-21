"""Per-output-route Planning argument composition boundary.

This operation preserves the existing PromptRef topology: the supplied writer is
invoked once per frozen output route. Tool identity/effect are never authored by
this operation or by the semantic writer result.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TypedDict


class ToolArgumentCandidateV1(TypedDict):
    schema_version: int
    route_id: str
    arguments: dict[str, object]
    evidence_refs: list[str]


ArgumentWriter = Callable[[Mapping[str, object]], ToolArgumentCandidateV1]


def compose_arguments_per_output_route(
    output_routes: Sequence[Mapping[str, object]],
    *,
    writer: ArgumentWriter,
) -> tuple[ToolArgumentCandidateV1, ...]:
    """Invoke the existing semantic writer independently for every frozen route."""
    if not output_routes:
        raise ValueError("ACTION planning requires at least one output route")
    route_ids: set[str] = set()
    candidates: list[ToolArgumentCandidateV1] = []
    for raw_route in output_routes:
        route_id = raw_route.get("route_id")
        if not isinstance(route_id, str) or not route_id:
            raise ValueError("route_id is required")
        if route_id in route_ids:
            raise ValueError("duplicate output route id")
        route_ids.add(route_id)
        candidate = writer(raw_route)
        if candidate.get("route_id") != route_id:
            raise ValueError("argument candidate escaped its frozen output route")
        if "arguments" not in candidate or not isinstance(candidate["arguments"], dict):
            raise ValueError("argument candidate requires business arguments")
        candidates.append(candidate)
    return tuple(candidates)
