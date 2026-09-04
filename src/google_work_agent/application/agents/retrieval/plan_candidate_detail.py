"""Deterministically plan candidate detail reads after metadata search."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import cast

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalQueryPlanV2,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)

_DETAIL_TOOL_BY_RESOURCE_TYPE = {
    "EMAIL": "gmail_get_thread",
    "GMAIL_THREAD": "gmail_get_thread",
    "GMAIL_MESSAGE": "gmail_get_message",
    "GMAIL_DRAFT": "gmail_get_draft",
    "GMAIL_ATTACHMENT": "gmail_get_attachment",
    "TASK": "tasks_get_task",
    "CALENDAR_EVENT": "calendar_get_event",
}


def deterministic_candidate_detail_plan(
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    detail_candidate_refs: Collection[str],
    attempted_detail_candidate_refs: Collection[str] = (),
) -> RetrievalQueryPlanV2 | None:
    """Choose one unread candidate per route when more Google evidence is required.

    Search result metadata establishes the candidate set. Selecting a candidate
    already judged relevant for a provider detail read is therefore a bounded
    deterministic continuation, not a new semantic query-planning decision.
    """

    if "current_round_no" not in prompt_input or not _needs_google_evidence(prompt_input):
        return None
    attempted = set(attempted_detail_candidate_refs)
    candidates = tuple(dict.fromkeys(detail_candidate_refs))
    route_queries: list[dict[str, object]] = []
    retrieval_order: list[str] = []
    for route in frozen_routes:
        detail_tool = _DETAIL_TOOL_BY_RESOURCE_TYPE.get(route["resource_type"])
        if detail_tool is None or detail_tool not in route["allowed_read_tool_ids"]:
            continue
        prefix = f"{route['resource_type'].lower()}:"
        candidate = next(
            (item for item in candidates if item.startswith(prefix) and item not in attempted),
            None,
        )
        if candidate is None:
            continue
        route_queries.append(
            {
                "route_id": route["route_id"],
                "operation": "DETAIL_FETCH",
                "reason_codes": ["CANDIDATE_DETAIL_REQUIRED"],
                "search_spec": None,
                "detail_candidate_ref": candidate,
            }
        )
        retrieval_order.append(route["route_id"])
    if not route_queries:
        return None
    return cast(
        RetrievalQueryPlanV2,
        {
            "schema_version": 2,
            "route_queries": route_queries,
            "required_information": ["candidate resource detail required by sufficiency"],
            "retrieval_order": retrieval_order,
        },
    )


def _needs_google_evidence(prompt_input: Mapping[str, object]) -> bool:
    issues = prompt_input.get("unresolved_sufficiency_issues")
    return isinstance(issues, list) and any(
        isinstance(issue, Mapping)
        and issue.get("required") is True
        and issue.get("resolution_source") == "GOOGLE"
        for issue in issues
    )


__all__ = ["deterministic_candidate_detail_plan"]
