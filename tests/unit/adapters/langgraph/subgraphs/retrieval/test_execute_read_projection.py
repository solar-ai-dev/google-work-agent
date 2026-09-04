from typing import cast

import pytest

from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    SourceFetchPlanV1,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)


@pytest.mark.parametrize(
    ("match_mode", "expected"),
    [
        ("PHRASE", '"프로젝트 일정"'),
        ("ALL", "프로젝트 일정"),
        ("ANY", "{프로젝트 일정}"),
    ],
)
def test_gmail_keyword_match_mode__lowers_to_distinct_provider_query(
    match_mode: str, expected: str
) -> None:
    plan = cast(
        SourceFetchPlanV1,
        {
            "resource_type": "GMAIL_THREAD",
            "operation_kind": "SEARCH",
            "effective_constraints": [
                {
                    "kind": "KEYWORD",
                    "terms": ["프로젝트", "일정"],
                    "match_mode": match_mode,
                }
            ],
        },
    )
    route = cast(
        InputToolRouteV1,
        {"allowed_read_tool_ids": ["gmail_search_threads"]},
    )

    tool_id, arguments = execute_read_projection.project_connector_call(
        plan, route=route, page_size=20
    )

    assert tool_id == "gmail_search_threads"
    assert arguments["query"] == expected
