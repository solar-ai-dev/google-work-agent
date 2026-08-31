from __future__ import annotations

import pytest
from evaluation.contracts.routing_trajectory_projection import RoutingTrajectoryProjectionV2
from pydantic import ValidationError


def test_routing_trajectory_is_diagnostic_only() -> None:
    trajectory = RoutingTrajectoryProjectionV2(
        schema_version=2,
        case_id="CASE-CORE-001",
        topology_scope="SIX_ROLE_BASELINE",
        observed_node_ids=["request.identify_goal"],
        observed_tool_ids=["gmail_get_thread"],
        skipped_node_ids=[],
        budget_snapshot={"llm_call_count": 1},
        diagnostic_only=True,
    )

    assert trajectory.diagnostic_only is True
    assert (
        RoutingTrajectoryProjectionV2.model_validate_json(trajectory.canonical_json(), strict=True)
        == trajectory
    )


def test_routing_trajectory_rejects_non_diagnostic_materialization() -> None:
    with pytest.raises(ValidationError):
        RoutingTrajectoryProjectionV2.model_validate(
            {
                "schema_version": 2,
                "case_id": "CASE-CORE-001",
                "topology_scope": "SIX_ROLE_BASELINE",
                "observed_node_ids": [],
                "observed_tool_ids": [],
                "skipped_node_ids": [],
                "budget_snapshot": {},
                "diagnostic_only": False,
            },
            strict=True,
        )
