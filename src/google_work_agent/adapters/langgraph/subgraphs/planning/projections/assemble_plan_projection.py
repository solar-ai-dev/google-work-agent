"""Exact input projection for deterministic plan assembly and validation."""

from collections.abc import Mapping, Sequence
from typing import TypedDict, cast

from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionDependencyCandidateV1,
    PlanningActionSeedV1,
)


class AssemblePlanInputV1(TypedDict):
    output_routes: list[dict[str, object]]
    action_seeds: list[PlanningActionSeedV1]
    dependency_candidates: list[ActionDependencyCandidateV1]
    evidence_refs: list[str]


def project_assemble_plan_input(state: Mapping[str, object]) -> AssemblePlanInputV1:
    output_plan = state.get("output_plan")
    seeds = state.get("__planning_action_seeds__")
    dependencies = state.get("dependency_candidates")
    if not isinstance(output_plan, Mapping):
        raise ValueError("output_plan is required")
    routes = _objects(output_plan.get("output_routes"), "output_routes")
    seed_items = _objects(seeds, "action_seeds")
    dependency_items = _objects(dependencies, "dependencies")
    refs = state.get("evidence_refs", [])
    if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
        raise ValueError("evidence_refs must be strings")
    return {
        "output_routes": routes,
        "action_seeds": cast(list[PlanningActionSeedV1], seed_items),
        "dependency_candidates": cast(list[ActionDependencyCandidateV1], dependency_items),
        "evidence_refs": list(refs),
    }


def _objects(value: object, name: str) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{name} items must be objects")
    return [dict(cast(Mapping[str, object], item)) for item in value]


__all__ = ["AssemblePlanInputV1", "project_assemble_plan_input"]
