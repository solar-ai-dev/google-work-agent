"""Thin adapter for deterministic planning.assemble_plan."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.adapters.langgraph.subgraphs.planning.projections.planning_projection import (
    project_planning_input,
)
from google_work_agent.application.agents.planning.assemble_plan import assemble_plan


def assemble_plan_node(state: Mapping[str, object]) -> dict[str, object]:
    projected = project_planning_input(state)
    artifact_id = projected.get("plan_artifact_id")
    revision = projected.get("plan_revision")
    based_on = projected.get("plan_based_on", ())
    action_seeds = projected.get("action_seeds")
    if not isinstance(artifact_id, str) or not isinstance(revision, int):
        raise ValueError("plan_artifact_id and plan_revision are required")
    if not isinstance(based_on, Sequence) or isinstance(based_on, (str, bytes)):
        raise ValueError("plan_based_on must be a sequence")
    if not isinstance(action_seeds, Sequence) or isinstance(action_seeds, (str, bytes)):
        raise ValueError("action_seeds are required")
    return {
        "plan_draft": assemble_plan(
            artifact_id=artifact_id,
            revision=revision,
            based_on=based_on,  # type: ignore[arg-type]
            action_seeds=action_seeds,  # type: ignore[arg-type]
        )
    }
