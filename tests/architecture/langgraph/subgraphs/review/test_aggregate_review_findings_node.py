# ruff: noqa: E501
from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.review.nodes.aggregate_review_findings_node import (
    aggregate_review_findings_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.projections.aggregate_review_findings_projection import (
    project_aggregate_review_findings_input,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_aggregate_review_findings import (
    route_after_aggregate_review_findings,
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
    assert "unrelated" not in project_aggregate_review_findings_input(state)
    patch = aggregate_review_findings_node(state)
    assert patch["review_result"]["status"] == "PASS"
    assert patch["workflow_signal"] is None
    assert route_after_aggregate_review_findings(patch) == "end"
