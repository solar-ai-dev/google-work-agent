from google_work_agent.application.orchestration.retrieval_attempts import build_query_attempt


def test_query_attempt_uses_bounded_query_and_page_identities() -> None:
    attempt = build_query_attempt(
        query_attempt_id="attempt-1",
        run_id="run-1",
        round_no=0,
        attempt_no=0,
        plan={
            "schema_version": 1,
            "route_id": "route-1",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "operation_kind": "SEARCH",
            "effective_constraints": [
                {"kind": "KEYWORD", "terms": ["roadmap"], "match_mode": "ANY"}
            ],
            "query_identity_hash": "query-hash",
            "prior_read_result_handle": None,
            "detail_candidate_ref": None,
        },
        tool_id="gmail_search_threads",
        canonical_arguments={"query": "roadmap", "page_size": 10},
        previous_query_hash=None,
        page_state_hash="page-hash",
        candidate_count=2,
        stop_reason="READ_COMPLETE",
    )

    assert attempt["operation_kind"] == "SEARCH"
    assert attempt["round_no"] == 0
    assert attempt["query_spec"]["canonical_arguments"]["query"] == "roadmap"
    assert "page_token" not in attempt
    assert "next_page_token" not in attempt
