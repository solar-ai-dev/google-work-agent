from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.review.projections import (
    project_review_signals_projection,
)
from google_work_agent.application.agents.review.aggregate_review_findings import (
    aggregate_review_findings,
)
from google_work_agent.application.agents.review.validate_review import validate_review
from google_work_agent.ports.system.contracts.workflow_handoff import AgentNodeResumeTargetV2

DIMENSION = "review.inspect_goal_and_evidence"


def _finding(kind: str) -> dict[str, object]:
    return {
        "dimension": DIMENSION,
        "code": f"{kind}_CODE",
        "finding_kind": kind,
        "description": f"{kind} description",
        "evidence_refs": ["e1"],
        "affected_action_ids": ["a1"],
        "affected_route_ids": ["r1"],
        "required_information": ["needed information"],
    }


def test_aggregate_and__validate_close_all__six_result_variants() -> None:
    expected = {
        None: ("PASS", "summary"),
        "ISSUE": ("REVISE", "issues"),
        "EVIDENCE_GAP": ("RETRIEVE_MORE", "evidence_gaps"),
        "ROUTE_ISSUE": ("ROUTE_RECONSIDERATION", "route_issues"),
        "CONFIRMATION": ("CONFIRM", "confirmation"),
        "BLOCKER": ("BLOCK", "blockers"),
    }
    for kind, (status, payload) in expected.items():
        result = aggregate_review_findings(
            [] if kind is None else [_finding(kind)],
            artifact_id=f"review-{status}",
            revision=1,
            based_on=[{"artifact_id": "plan-1", "revision": 1}],
        )
        assert validate_review(result)["status"] == status
        assert payload in result


def test_closed_precedence__is_safety__first_and_deterministic() -> None:
    result = aggregate_review_findings(
        [
            _finding("ISSUE"),
            _finding("EVIDENCE_GAP"),
            _finding("CONFIRMATION"),
            _finding("BLOCKER"),
        ],
        artifact_id="review-1",
        revision=1,
    )
    assert result["status"] == "BLOCK"


def test_nonlocal_dispositions_project__typed_signals_and__pass_revise_do_not() -> None:
    pass_result = aggregate_review_findings([], artifact_id="review-pass", revision=1)
    revise = aggregate_review_findings([_finding("ISSUE")], artifact_id="review-revise", revision=1)
    assert project_review_signals_projection.project_review_workflow_signal_v2(pass_result) is None
    assert project_review_signals_projection.project_review_workflow_signal_v2(revise) is None

    retrieval = aggregate_review_findings(
        [_finding("EVIDENCE_GAP")], artifact_id="review-r", revision=1
    )
    route = aggregate_review_findings(
        [_finding("ROUTE_ISSUE")], artifact_id="review-route", revision=1
    )
    block = aggregate_review_findings([_finding("BLOCKER")], artifact_id="review-block", revision=1)
    retrieval_signal = project_review_signals_projection.project_review_workflow_signal_v2(
        retrieval
    )
    route_signal = project_review_signals_projection.project_review_workflow_signal_v2(route)
    block_signal = project_review_signals_projection.project_review_workflow_signal_v2(block)
    assert retrieval_signal is not None and retrieval_signal["kind"] == "RETRIEVAL_REQUIRED"
    assert route_signal is not None and route_signal["kind"] == "ROUTE_RECONSIDERATION_REQUIRED"
    assert block_signal is not None and block_signal["kind"] == "BLOCKED"

    confirmation = aggregate_review_findings(
        [_finding("CONFIRMATION")], artifact_id="review-c", revision=1
    )
    target = AgentNodeResumeTargetV2(
        kind="AGENT_NODE",
        semantic_owner_id="REVIEW",
        compiled_subgraph_id="SIX_REVIEW",
        node_id="review.aggregate_findings",
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="resume-contract-v1",
    )
    signal = project_review_signals_projection.project_review_workflow_signal_v2(
        confirmation,
        interrupt_id="interrupt-1",
        resume_target=target,
    )
    assert signal is not None
    assert signal["kind"] == "CONFIRMATION_REQUIRED"
    assert signal["resume_target"] == target
