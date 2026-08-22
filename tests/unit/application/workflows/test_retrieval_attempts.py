from google_work_agent.application.orchestration.retrieval_attempts import build_query_attempt


def test_query_attempt_uses_bounded_query_and_page_identities() -> None:
    attempt = build_query_attempt(
        query_attempt_id="attempt-1",
        run_id="run-1",
        route_id="route-1",
        round_no=0,
        attempt_no=0,
        plan={
            "schema_version": 2,
            "source": "GMAIL",
            "priority": 1,
            "reason_codes": [],
            "constraints": {"topic": "roadmap"},
            "page_size": 10,
            "max_pages": 1,
            "max_candidates": 10,
            "detail_limit": 1,
            "required": True,
            "calendar_read_mode": None,
            "temporal_query": None,
        },
        connector_id="google_workspace",
        operation_kind="SEARCH",
        query_hash="query-hash",
        previous_query_hash=None,
        page_state_hash="page-hash",
        candidate_count=2,
        stop_reason="READ_COMPLETE",
    )

    assert attempt["operation_kind"] == "SEARCH"
    assert attempt["round_no"] == 0
    assert attempt["query_spec"]["query_hash"] == "query-hash"
    assert "page_token" not in attempt
    assert "next_page_token" not in attempt
