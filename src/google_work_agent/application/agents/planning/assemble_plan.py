"""Assemble one canonical Planning action plan from prepared action seeds."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Literal, cast

from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionDependencyCandidateV1,
    ActionPlanDraftV2,
    PlanningActionSeedV1,
    StateArtifactRefV1,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    ToolArgumentCandidateV1,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    OutputToolRouteV1,
)


def materialize_action_seeds(
    *,
    output_routes: Iterable[OutputToolRouteV1],
    argument_candidates: Iterable[ToolArgumentCandidateV1],
    action_id_factory: Callable[[], str],
) -> tuple[PlanningActionSeedV1, ...]:
    routes = tuple(output_routes)
    candidates = tuple(argument_candidates)
    by_route = {candidate["route_id"]: candidate for candidate in candidates}
    if len(by_route) != len(candidates) or {r["route_id"] for r in routes} != set(by_route):
        raise ValueError("argument candidates must match frozen output routes")
    seeds: list[PlanningActionSeedV1] = []
    for route in routes:
        candidate = by_route[route["route_id"]]
        seeds.append(
            {
                "action_id": action_id_factory(),
                "route_id": route["route_id"],
                "tool_id": route["selected_tool_id"],
                "effect": cast(Literal["CREATE", "UPDATE", "SEND", "DELETE"], route["effect"]),
                "arguments": dict(candidate["arguments"]),
                "evidence_refs": list(candidate["evidence_refs"]),
            }
        )
    if any(not seed["action_id"] for seed in seeds) or len({s["action_id"] for s in seeds}) != len(
        seeds
    ):
        raise ValueError("action id factory must produce unique non-empty ids")
    return tuple(seeds)


def assemble_plan(
    *,
    artifact_id: str,
    revision: int,
    based_on: Iterable[StateArtifactRefV1],
    action_seeds: Iterable[PlanningActionSeedV1],
    dependency_candidates: Iterable[ActionDependencyCandidateV1],
) -> ActionPlanDraftV2:
    """Assemble a plan from the dependency candidates produced by the prior node."""
    if not artifact_id:
        raise ValueError("artifact_id must not be empty")
    if revision < 1:
        raise ValueError("revision must be at least 1")
    seeds = tuple(action_seeds)
    if not seeds:
        raise ValueError("action plan requires at least one action")
    action_ids = [item["action_id"] for item in seeds]
    if len(action_ids) != len(set(action_ids)):
        raise ValueError("duplicate action_id")
    route_ids = [item["route_id"] for item in seeds]
    if len(route_ids) != len(set(route_ids)):
        raise ValueError("duplicate route_id")

    dependency_items = tuple(dependency_candidates)
    by_action: dict[str, list[str]] = {action_id: [] for action_id in action_ids}
    for item in dependency_items:
        action_id = item["action_id"]
        predecessor = item["depends_on_action_id"]
        if action_id not in by_action or predecessor not in by_action:
            raise ValueError("dependency escapes the plan")
        if action_id == predecessor:
            raise ValueError("action cannot depend on itself")
        if predecessor not in by_action[action_id]:
            by_action[action_id].append(predecessor)
    _validate_acyclic(by_action)
    return {
        "schema_version": 2,
        "meta": {
            "artifact_id": artifact_id,
            "revision": revision,
            "based_on": [cast(StateArtifactRefV1, dict(ref)) for ref in based_on],
        },
        "actions": [
            {
                "action_id": seed["action_id"],
                "route_id": seed["route_id"],
                "tool_id": seed["tool_id"],
                "effect": seed["effect"],
                "arguments": dict(seed["arguments"]),
                "evidence_refs": list(seed["evidence_refs"]),
                "depends_on_action_ids": list(by_action[seed["action_id"]]),
            }
            for seed in seeds
        ],
    }


__all__ = ["assemble_plan", "materialize_action_seeds"]


def _validate_acyclic(edges: dict[str, list[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(action_id: str) -> None:
        if action_id in visiting:
            raise ValueError("action dependency cycle")
        if action_id in visited:
            return
        visiting.add(action_id)
        for predecessor in edges[action_id]:
            visit(predecessor)
        visiting.remove(action_id)
        visited.add(action_id)

    for action_id in edges:
        visit(action_id)
