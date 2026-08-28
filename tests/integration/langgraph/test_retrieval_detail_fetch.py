"""Compiled context_retriever subgraph coverage for RetrievalOperationV2 DETAIL_FETCH.

Pre-Prompt Runtime Closure item 5: production wiring for DETAIL_FETCH is
already judged present -- this proves the full compiled trajectory
(SEARCH -> bounded candidate -> DETAIL_FETCH -> detail target binding ->
MCP detail read -> segment -> RAG -> Evidence -> Sufficiency ->
RetrievalResult) works end to end and never leaks a raw provider id, page
token, or query string into the typed RetrievalResultV1.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.integration.langgraph.test_runtime import (
    FIXTURE_ROOT,
    FakeGoogleGateway,
    GraphProfile,
    ProductFixtureSnapshotLoader,
    _clear_intent,
    _llm_result,
    _make_runtime_with_llm,
    _QueuedLLMRuntime,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _start_request,
    _sufficiency_output,
)


def _detail_fetch_plan_query(route_id: str, *, detail_candidate_ref: str) -> dict[str, object]:
    return {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": route_id,
                "operation": "DETAIL_FETCH",
                "reason_codes": ["REQUIRED"],
                "search_spec": None,
                "detail_candidate_ref": detail_candidate_ref,
            }
        ],
        "required_information": ["detail-fetch-followup"],
        "retrieval_order": [route_id],
    }


def test_detail_fetch_followup_round_reaches_retrieval_result_without_leakage(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path, status="ANALYZING")
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    llm_runtime = _QueuedLLMRuntime([])
    runtime = _make_runtime_with_llm(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-detail-fetch.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
        default_tasklist_id="task-list-default",
    )
    try:
        state = runtime._initial_state(_start_request())  # noqa: SLF001
        state["request_intent"] = _clear_intent()
        state["request_intent"]["meta"] = {"artifact_id": "intent-1", "revision": 1, "based_on": []}
        routed = runtime._tool_route_subgraph.invoke(state)  # noqa: SLF001
        input_routes = routed["tool_route_plan"]["input_plan"]["input_routes"]
        task_routes = [route for route in input_routes if route["resource_type"] == "TASK"]
        assert len(task_routes) == 1
        route_id = task_routes[0]["route_id"]

        # SEARCH candidate handles are only known once round 1 actually
        # fetched them, so the DETAIL_FETCH queue entry is appended after
        # Tool Route froze the real route_id, matching the FREEBUSY test's
        # pattern for the same reason.
        llm_runtime._queued.extend(  # noqa: SLF001
            [
                _llm_result(_selection_output()),
                _llm_result(_sufficiency_output("NEEDS_MORE_DATA")),
                _llm_result(
                    _detail_fetch_plan_query(route_id, detail_candidate_ref="task:task-billing")
                ),
                _llm_result(_selection_output()),
                _llm_result(_sufficiency_output("SUFFICIENT")),
            ]
        )

        context = runtime._context_subgraph.invoke(routed)  # noqa: SLF001

        assert context["__target__"] == "work_analysis"
        retrieval_result = context["retrieval_result"]
        assert retrieval_result is not None
        assert gateway.count_calls("get_task") >= 1

        plan_query_calls = [
            call
            for call in llm_runtime.calls
            if getattr(call["prompt_ref"], "prompt_id", None) == "retrieval.plan_query"
        ]
        assert len(plan_query_calls) == 2

        serialized = json.dumps(retrieval_result, sort_keys=True)
        for leaked in ("page_token", "task-list-default", "query_identity_hash"):
            assert leaked not in serialized
    finally:
        runtime.close()
