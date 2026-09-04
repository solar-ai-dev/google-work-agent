from typing import cast

from google_work_agent.application.agents.retrieval.contracts.query_attempt import (
    QueryAttemptV1,
)
from google_work_agent.application.agents.retrieval.project_attempted_detail_refs import (
    project_attempted_detail_refs,
)


def test_project_attempted_detail_refs__keeps_all_completed_detail_rounds() -> None:
    attempts = [
        _attempt("SEARCH", "gmail_search_threads", {"query": "KAN-93"}, "COMPLETE"),
        _attempt("DETAIL_FETCH", "gmail_get_thread", {"thread_id": "first"}, "COMPLETE"),
        _attempt("DETAIL_FETCH", "gmail_get_thread", {"thread_id": "second"}, "COMPLETE"),
        _attempt("DETAIL_FETCH", "gmail_get_thread", {"thread_id": "first"}, "COMPLETE"),
        _attempt("DETAIL_FETCH", "gmail_get_thread", {"thread_id": "unfinished"}, None),
    ]

    assert project_attempted_detail_refs(attempts) == [
        "gmail_thread:first",
        "gmail_thread:second",
    ]


def _attempt(
    operation_kind: str,
    tool_id: str,
    arguments: dict[str, str],
    stop_reason: str | None,
) -> QueryAttemptV1:
    return cast(
        QueryAttemptV1,
        {
            "schema_version": 1,
            "query_attempt_id": f"attempt-{tool_id}-{arguments}",
            "run_id": "run-1",
            "route_id": "route-1",
            "round_no": 1,
            "attempt_no": 1,
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "operation_kind": operation_kind,
            "normalized_intent_constraints": [],
            "query_spec": {
                "tool_id": tool_id,
                "tool_schema_version": "v1",
                "canonical_arguments": arguments,
            },
            "previous_query_hash": None,
            "page_state_hash": None,
            "added_constraints": [],
            "removed_constraints": [],
            "change_reason_code": None,
            "candidate_count": None,
            "top_score": None,
            "score_margin": None,
            "confidence_band": None,
            "retrieval_config_version": "test",
            "score_config_version": "test",
            "threshold_config_version": "test",
            "stop_reason": stop_reason,
        },
    )
