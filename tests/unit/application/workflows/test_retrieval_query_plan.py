from typing import cast

import pytest

from google_work_agent.application.workflows.handoff_contracts import SufficiencyIssueV2
from google_work_agent.application.workflows.retrieval_query_plan import (
    FollowupQueryPlanValidationError,
    validate_followup_route_query_intent,
)
from google_work_agent.application.workflows.tool_routing import ToolRoutePlanV2


def test_followup_search_requires_frozen_route_reason_and_semantic_delta() -> None:
    result = validate_followup_route_query_intent(
        value={
            "route_id": "route-1",
            "operation_kind": "SEARCH",
            "reason_codes": ["MISSING_SUBJECT"],
            "constraint_delta": {"added_constraints": ["subject"], "removed_constraints": []},
            "detail_candidate_ref": None,
        },
        frozen_route=cast(ToolRoutePlanV2, _route_plan()),
        unresolved_issues=[cast(SufficiencyIssueV2, _issue())],
        detail_candidate_refs=frozenset(),
    )
    assert result["operation_kind"] == "SEARCH"


@pytest.mark.parametrize(
    "value",
    [
        {
            "route_id": "other", "operation_kind": "NEXT_PAGE",
            "reason_codes": ["MISSING_SUBJECT"], "constraint_delta": None,
            "detail_candidate_ref": None,
        },
        {
            "route_id": "route-1", "operation_kind": "SEARCH",
            "reason_codes": ["MISSING_SUBJECT"],
            "constraint_delta": {"added_constraints": [], "removed_constraints": []},
            "detail_candidate_ref": None,
        },
        {
            "route_id": "route-1", "operation_kind": "DETAIL_FETCH",
            "reason_codes": ["MISSING_SUBJECT"], "constraint_delta": None,
            "detail_candidate_ref": "external-id",
        },
        {
            "route_id": "route-1", "operation_kind": "NEXT_PAGE",
            "reason_codes": ["MISSING_SUBJECT"], "constraint_delta": None,
            "detail_candidate_ref": None, "page_token": "raw",
        },
    ],
)
def test_invalid_followup_output_fails_closed(value: object) -> None:
    with pytest.raises(FollowupQueryPlanValidationError):
        validate_followup_route_query_intent(
            value=value,
            frozen_route=cast(ToolRoutePlanV2, _route_plan()),
            unresolved_issues=[cast(SufficiencyIssueV2, _issue())],
            detail_candidate_refs=frozenset({"candidate-1"}),
        )


def _route_plan() -> dict[str, object]:
    return {
        "input_plan": {
            "input_routes": [
                {"route_id": "route-1", "allowed_read_tool_ids": ["gmail_search_messages"]}
            ]
        }
    }


def _issue() -> dict[str, object]:
    return {
        "slot": "subject",
        "issue_type": "MISSING",
        "required": True,
        "resolution_source": "GOOGLE",
        "safety_critical": False,
        "reason_codes": ["MISSING_SUBJECT"],
    }
