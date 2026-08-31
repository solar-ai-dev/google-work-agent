"""Thin adapter for deterministic planning.assemble_plan."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

from google_work_agent.adapters.langgraph.subgraphs.planning.projections import (
    assemble_plan_projection,
)
from google_work_agent.application.agents.planning.assemble_plan import assemble_plan
from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    StateArtifactRefV1,
)
from google_work_agent.application.agents.planning.validate_plan import validate_plan


def assemble_plan_node(
    state: Mapping[str, object],
    *,
    artifact_id_factory: Callable[[], str],
    based_on: list[StateArtifactRefV1],
) -> dict[str, object]:
    projected = assemble_plan_projection.project_assemble_plan_input(state)
    plan = assemble_plan(
        artifact_id=artifact_id_factory(),
        revision=1,
        based_on=based_on,
        action_seeds=projected["action_seeds"],
        dependency_candidates=projected["dependency_candidates"],
    )
    return {
        "final_result": validate_plan(
            plan,
            output_routes=projected["output_routes"],
            allowed_evidence_refs=set(cast(list[str], projected["evidence_refs"])),
        )
    }
