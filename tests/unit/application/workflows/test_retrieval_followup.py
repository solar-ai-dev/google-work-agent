import pytest

from google_work_agent.application.workflows.api_acquisition import retrieval_query_hash
from google_work_agent.application.workflows.retrieval_followup import (
    ChangedSearchProposal,
    FollowupValidationError,
    validate_changed_search,
)


def test_changed_search_requires_issue_link_and_semantic_change() -> None:
    plan = {
        "schema_version": 2, "source": "GMAIL", "priority": 1, "reason_codes": [],
        "constraints": {"topic": "roadmap"}, "page_size": 10, "max_pages": 1,
        "max_candidates": 10, "detail_limit": 1, "required": True,
        "calendar_read_mode": None, "temporal_query": None,
    }
    proposal = ChangedSearchProposal(
        route_id="route-1", plan=plan, previous_query_hash="old",
        added_constraints=("topic",), removed_constraints=(), change_reason_code="MISSING_TOPIC",
    )
    route = {"input_plan": {"input_routes": [{"route_id": "route-1"}]}}
    issue = {
        "slot": "topic", "issue_type": "MISSING", "required": True,
        "resolution_source": "GOOGLE", "safety_critical": False,
        "reason_codes": ["MISSING_TOPIC"],
    }
    assert validate_changed_search(proposal=proposal, frozen_route=route, unresolved_issues=[issue])
    unchanged = ChangedSearchProposal(
        "route-1", plan, retrieval_query_hash(plan), (), (), "MISSING_TOPIC"
    )
    with pytest.raises(FollowupValidationError, match="QUERY_REPEATED"):
        validate_changed_search(proposal=unchanged, frozen_route=route, unresolved_issues=[issue])
