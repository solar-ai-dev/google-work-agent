from __future__ import annotations

from typing import cast

from google_work_agent.adapters.langgraph.subgraphs.review.nodes import (
    aggregate_review_findings_node as aggregate_node_module,
)
from google_work_agent.adapters.langgraph.subgraphs.review.projections import (
    aggregate_review_findings_projection as aggregate_projection_module,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing import (
    route_after_aggregate_review_findings as aggregate_route_module,
)


def test_aggregate_node_owns_aggregation_and_validation_without_pseudo_node() -> None:
    state = {
        "review_phase": "INITIAL",
        "review_artifact_id": "review-1",
        "review_revision": 1,
        "review_based_on": [],
        "goal_evidence_result": {
            "schema_version": 1,
            "dimension": "review.inspect_goal_and_evidence",
            "findings": [],
        },
        "unrelated": "excluded",
    }
    assert "unrelated" not in aggregate_projection_module.project_aggregate_review_findings_input(
        state
    )
    patch = aggregate_node_module.aggregate_review_findings_node(state)
    review_result = cast(dict[str, object], patch["review_result"])
    assert review_result["status"] == "PASS"
    assert patch["workflow_signal"] is None
    assert aggregate_route_module.route_after_aggregate_review_findings(patch) == "end"
