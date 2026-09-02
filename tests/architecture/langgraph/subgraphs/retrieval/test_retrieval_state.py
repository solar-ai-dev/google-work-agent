from pathlib import Path


def test_retrieval_state__v2_declares__exact_semantic_fields() -> None:
    root = Path(__file__).resolve().parents[5]
    source = (
        root / "src/google_work_agent/adapters/langgraph/subgraphs/retrieval/state.py"
    ).read_text()
    expected = {
        "request_intent",
        "input_route_ref",
        "input_routes",
        "query_plan",
        "query_attempts",
        "source_statuses",
        "read_result_handles",
        "segment_handles",
        "availability_results",
        "rag_candidates",
        "exclusion_obligation_segment_ids",
        "pending_user_retrieval_need",
        "evidence_selection",
        "sufficiency",
        "final_result",
    }
    annotations = __import__(
        "google_work_agent.adapters.langgraph.subgraphs.retrieval.state",
        fromlist=["RetrievalState"],
    ).RetrievalState.__annotations__
    assert set(annotations) == expected
    assert "operation_inputs" not in source
