from typing import cast

from google_work_agent.application.agents.retrieval.build_query import (
    RouteConstraintPolicy,
    build_query,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.orchestration.retrieval_v2_contracts import RetrievalQueryPlanV2


def test_build_query_preserves_exact_frozen_resource_type() -> None:
    route = cast(
        InputToolRouteV1,
        {
            "route_id": "r1",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        },
    )
    plan = cast(
        RetrievalQueryPlanV2,
        {
            "schema_version": 2,
            "route_queries": [
                {
                    "route_id": "r1",
                    "operation": "SEARCH",
                    "reason_codes": ["USER_REQUEST"],
                    "search_spec": {
                        "mode": "INITIAL",
                        "constraints": [
                            {"kind": "KEYWORD", "terms": ["alpha"], "match_mode": "ANY"}
                        ],
                    },
                    "detail_candidate_ref": None,
                }
            ],
            "required_information": ["mail"],
            "retrieval_order": ["r1"],
        },
    )

    result = build_query(
        plan,
        frozen_routes=[route],
        route_policies={"r1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
    )

    assert result[0]["resource_type"] == "GMAIL_THREAD"
