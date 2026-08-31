"""Exact input projection for deterministic dependency derivation."""

from collections.abc import Mapping, Sequence
from typing import TypedDict, cast

from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    PlanningActionSeedV1,
)


class BuildDependenciesInputV1(TypedDict):
    action_seeds: list[PlanningActionSeedV1]


def project_build_dependencies_input(state: Mapping[str, object]) -> BuildDependenciesInputV1:
    seeds = state.get("__planning_action_seeds__")
    if not isinstance(seeds, Sequence) or isinstance(seeds, (str, bytes)):
        raise ValueError("action seeds are required")
    if not all(isinstance(item, Mapping) for item in seeds):
        raise ValueError("action seeds must be objects")
    return {"action_seeds": cast(list[PlanningActionSeedV1], [dict(item) for item in seeds])}


__all__ = ["BuildDependenciesInputV1", "project_build_dependencies_input"]
