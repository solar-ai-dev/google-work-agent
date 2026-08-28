from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.orchestration.api_acquisition import RetrievalBudget
from google_work_agent.application.orchestration.retrieval_v2_contracts import SourceFetchPlanV1
from google_work_agent.application.orchestration.source_fetch_plan_execution_projection import (
    project_for_legacy_read_executor,
)


def test_projection_preserves_v2_planner_as_only_planning_authority() -> None:
    result = project_for_legacy_read_executor(
        [_v2_plan()], frozen_routes=[_route()], retrieval_budget=RetrievalBudget()
    )

    assert result == [
        {
            "schema_version": 2,
            "source": "GMAIL",
            "priority": 1,
            "reason_codes": ["MISSING_INVOICE"],
            "constraints": {"query": "invoice renewal"},
            "page_size": 20,
            "max_pages": 1,
            "max_candidates": 20,
            "detail_limit": 10,
            "required": True,
            "calendar_read_mode": None,
            "temporal_query": None,
        }
    ]


def test_projection_deterministically_translates_email_temporal_constraint() -> None:
    plan = _v2_plan()
    plan["effective_constraints"] = [
        {
            "kind": "TEMPORAL_RANGE",
            "axis": "MESSAGE_TIME",
            "start_local": "2026-08-15T09:00:00",
            "end_local": None,
            "timezone": "Asia/Seoul",
        }
    ]

    result = project_for_legacy_read_executor(
        [plan], frozen_routes=[_route()], retrieval_budget=RetrievalBudget()
    )

    assert result[0]["constraints"] == {"query": "after:2026/08/15"}


def _route() -> InputToolRouteV1:
    return {
        "route_id": "route-1",
        "connector_id": "google_workspace",
        "resource_type": "GMAIL_THREAD",
        "allowed_read_tool_ids": ["gmail_search_threads"],
        "required": True,
        "reason_codes": ["MISSING_INVOICE"],
    }


def _v2_plan() -> SourceFetchPlanV1:
    return {
        "schema_version": 1,
        "route_id": "route-1",
        "connector_id": "google_workspace",
        "resource_type": "EMAIL",
        "operation_kind": "SEARCH",
        "effective_constraints": [
            {"kind": "KEYWORD", "terms": ["invoice", "renewal"], "match_mode": "ANY"}
        ],
        "query_identity_hash": "hash",
        "prior_read_result_handle": None,
        "detail_candidate_ref": None,
    }
