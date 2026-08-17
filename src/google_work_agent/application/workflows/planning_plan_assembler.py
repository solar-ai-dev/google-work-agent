"""Deterministic assembly of canonical Planning ActionPlanDraftV2.

LLM argument candidates contribute only business arguments/evidence references.
Frozen Tool Route contributes connector-independent route/tool/effect identity.
Dependency candidates may be produced conditionally, but DAG validation and the
final typed plan are deterministic code responsibilities.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Literal, Required, TypedDict, cast

from google_work_agent.application.workflows.planning_arguments import ToolArgumentCandidateV1
from google_work_agent.application.workflows.tool_routing import OutputToolRouteV1


class PlanningAssemblyError(ValueError):
    """Raised when Planning candidates cannot form one frozen canonical plan."""


class StateArtifactRefV1(TypedDict):
    artifact_id: str
    revision: int


class StateArtifactMetaV1(TypedDict):
    artifact_id: str
    revision: int
    based_on: list[StateArtifactRefV1]


class ActionDependencyCandidateV1(TypedDict):
    action_id: str
    depends_on_action_id: str
    reason: str


class PlannedActionV2(TypedDict):
    action_id: str
    route_id: str
    tool_id: str
    effect: Literal["CREATE", "UPDATE", "SEND", "DELETE"]
    arguments: dict[str, object]
    evidence_refs: list[str]
    depends_on_action_ids: list[str]


class ActionPlanDraftV2(TypedDict):
    schema_version: Required[Literal[2]]
    meta: StateArtifactMetaV1
    actions: list[PlannedActionV2]


class PlanningActionSeedV1(TypedDict):
    action_id: str
    route_id: str
    tool_id: str
    effect: Literal["CREATE", "UPDATE", "SEND", "DELETE"]
    arguments: dict[str, object]
    evidence_refs: list[str]


_WRITE_EFFECTS = frozenset({"CREATE", "UPDATE", "SEND", "DELETE"})


def materialize_action_seeds(
    *,
    output_routes: Iterable[OutputToolRouteV1],
    argument_candidates: Iterable[ToolArgumentCandidateV1],
    action_id_factory: Callable[[], str],
) -> tuple[PlanningActionSeedV1, ...]:
    """Join exactly one argument candidate to each frozen output route."""

    routes = tuple(output_routes)
    candidates = tuple(argument_candidates)
    route_by_id = _unique_routes(routes)
    candidate_by_route = _unique_candidates(candidates)

    missing = set(route_by_id) - set(candidate_by_route)
    extra = set(candidate_by_route) - set(route_by_id)
    if missing or extra:
        raise PlanningAssemblyError(
            f"argument candidates must match frozen output routes; missing={sorted(missing)}, "
            f"extra={sorted(extra)}"
        )

    seeds: list[PlanningActionSeedV1] = []
    for route in routes:
        route_id = route["route_id"]
        candidate = candidate_by_route[route_id]
        effect = route["effect"]
        if effect not in _WRITE_EFFECTS:
            raise PlanningAssemblyError(f"output route is not a write effect: {route_id}")
        action_id = action_id_factory()
        if not action_id:
            raise PlanningAssemblyError("action id factory returned an empty id")
        seeds.append(
            {
                "action_id": action_id,
                "route_id": route_id,
                "tool_id": route["selected_tool_id"],
                "effect": cast(Literal["CREATE", "UPDATE", "SEND", "DELETE"], effect),
                "arguments": dict(candidate["arguments"]),
                "evidence_refs": list(candidate["evidence_refs"]),
            }
        )
    if len({seed["action_id"] for seed in seeds}) != len(seeds):
        raise PlanningAssemblyError("action id factory produced duplicate ids")
    return tuple(seeds)


def assemble_action_plan_draft_v2(
    *,
    artifact_id: str,
    revision: int,
    based_on: Iterable[StateArtifactRefV1],
    action_seeds: Iterable[PlanningActionSeedV1],
    dependency_candidates: Iterable[ActionDependencyCandidateV1] = (),
) -> ActionPlanDraftV2:
    """Validate dependencies and assemble the final immutable Planning artifact."""

    if not artifact_id:
        raise PlanningAssemblyError("artifact_id must not be empty")
    if revision < 1:
        raise PlanningAssemblyError("revision must be at least 1")
    seeds = tuple(action_seeds)
    if not seeds:
        raise PlanningAssemblyError("action plan requires at least one action")
    action_ids = [seed["action_id"] for seed in seeds]
    if len(set(action_ids)) != len(action_ids):
        raise PlanningAssemblyError("duplicate action_id in action seeds")

    dependencies_by_action: dict[str, list[str]] = {action_id: [] for action_id in action_ids}
    seen_edges: set[tuple[str, str]] = set()
    for candidate in dependency_candidates:
        action_id = candidate["action_id"]
        dependency_id = candidate["depends_on_action_id"]
        if action_id not in dependencies_by_action or dependency_id not in dependencies_by_action:
            raise PlanningAssemblyError("dependency references an action outside this plan")
        if action_id == dependency_id:
            raise PlanningAssemblyError("action cannot depend on itself")
        edge = (action_id, dependency_id)
        if edge in seen_edges:
            continue
        seen_edges.add(edge)
        dependencies_by_action[action_id].append(dependency_id)

    _validate_acyclic(dependencies_by_action)
    actions: list[PlannedActionV2] = [
        {
            "action_id": seed["action_id"],
            "route_id": seed["route_id"],
            "tool_id": seed["tool_id"],
            "effect": seed["effect"],
            "arguments": dict(seed["arguments"]),
            "evidence_refs": list(seed["evidence_refs"]),
            "depends_on_action_ids": list(dependencies_by_action[seed["action_id"]]),
        }
        for seed in seeds
    ]
    return {
        "schema_version": 2,
        "meta": {
            "artifact_id": artifact_id,
            "revision": revision,
            "based_on": [dict(ref) for ref in based_on],  # type: ignore[list-item]
        },
        "actions": actions,
    }


def _unique_routes(routes: tuple[OutputToolRouteV1, ...]) -> dict[str, OutputToolRouteV1]:
    result: dict[str, OutputToolRouteV1] = {}
    for route in routes:
        route_id = route["route_id"]
        if route_id in result:
            raise PlanningAssemblyError(f"duplicate frozen output route: {route_id}")
        result[route_id] = route
    if not result:
        raise PlanningAssemblyError("ACTION planning requires frozen output routes")
    return result


def _unique_candidates(
    candidates: tuple[ToolArgumentCandidateV1, ...],
) -> dict[str, ToolArgumentCandidateV1]:
    result: dict[str, ToolArgumentCandidateV1] = {}
    for candidate in candidates:
        route_id = candidate["route_id"]
        if route_id in result:
            raise PlanningAssemblyError(f"duplicate argument candidate: {route_id}")
        result[route_id] = candidate
    return result


def _validate_acyclic(dependencies: dict[str, list[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(action_id: str) -> None:
        if action_id in visited:
            return
        if action_id in visiting:
            raise PlanningAssemblyError("action dependency cycle detected")
        visiting.add(action_id)
        for dependency_id in dependencies[action_id]:
            visit(dependency_id)
        visiting.remove(action_id)
        visited.add(action_id)

    for action_id in dependencies:
        visit(action_id)


__all__ = [
    "ActionDependencyCandidateV1",
    "ActionPlanDraftV2",
    "PlannedActionV2",
    "PlanningActionSeedV1",
    "PlanningAssemblyError",
    "StateArtifactMetaV1",
    "StateArtifactRefV1",
    "assemble_action_plan_draft_v2",
    "materialize_action_seeds",
]
