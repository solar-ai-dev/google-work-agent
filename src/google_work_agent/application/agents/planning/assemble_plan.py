"""Assemble one canonical Planning action plan from prepared action seeds."""

from __future__ import annotations

from collections.abc import Iterable

from google_work_agent.application.agents.planning.build_dependencies import build_dependencies
from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionPlanDraftV2,
    PlanningActionSeedV1,
    StateArtifactRefV1,
)


def assemble_plan(
    *,
    artifact_id: str,
    revision: int,
    based_on: Iterable[StateArtifactRefV1],
    action_seeds: Iterable[PlanningActionSeedV1],
) -> ActionPlanDraftV2:
    """Assemble a plan using planning.build_dependencies as the sole dependency authority."""
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

    dependency_items = build_dependencies(seeds)
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
        "meta": {"artifact_id": artifact_id, "revision": revision, "based_on": [dict(ref) for ref in based_on]},  # type: ignore[typeddict-item]
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
