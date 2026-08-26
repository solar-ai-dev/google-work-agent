"""Compiled context_retriever subgraph coverage for RetrievalOperationV2 FREEBUSY.

Pre-Prompt Runtime Closure item 3: a CALENDAR FREEBUSY route_query must
deterministically validate/normalize into a SourceFetchPlanV1, execute
through the existing MCP ``calendar_query_freebusy`` tool, and materialize
into Evidence/Sufficiency without an uncaught exception -- for the FOLLOWUP
round (the INITIAL round always synthesizes a plain SEARCH in this fixture
suite; see ``_QueuedLLMRuntime._invoke``'s ``retrieval.plan_query`` special
case in ``test_runtime.py``).
"""

from __future__ import annotations

from pathlib import Path

from tests.integration.langgraph.test_runtime import (
    FIXTURE_ROOT,
    DeterministicUUID,
    FakeClockPort,
    FakeGoogleGateway,
    McpConnectorWriteAdapter,
    GraphProfile,
    LangGraphWorkflowRuntime,
    ProductFixtureSnapshotLoader,
    _action_intent,
    _llm_result,
    _QueuedLLMRuntime,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _start_request,
    _sufficiency_output,
    _tool_catalog,
    sqlite_unit_of_work_factory,
)


def _freebusy_plan_query(route_ids: list[str]) -> dict[str, object]:
    return {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": route_id,
                "operation": "FREEBUSY",
                "reason_codes": ["REQUIRED"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "TEMPORAL_RANGE",
                            "axis": "AVAILABILITY_WINDOW",
                            "start_local": "2026-11-01T00:00:00",
                            "end_local": "2026-11-02T00:00:00",
                            "timezone": "America/Los_Angeles",
                        }
                    ],
                },
                "detail_candidate_ref": None,
            }
            for route_id in route_ids
        ],
        "required_information": ["freebusy-availability-window"],
        "retrieval_order": route_ids,
    }


def test_freebusy_followup_round_executes_without_uncaught_exception(
    tmp_path: Path,
) -> None:
    """INITIAL round SEARCHes calendar events (synthesized), NEEDS_MORE_DATA
    triggers a FOLLOWUP round whose queued plan_query selects FREEBUSY --
    that round must reach finalize (through the real calendar_query_freebusy
    MCP tool) rather than crash or be silently dropped."""
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path, status="ANALYZING")
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    llm_runtime = _QueuedLLMRuntime([])
    runtime = LangGraphWorkflowRuntime(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        llm_runtime=llm_runtime,
        gateway=gateway,
        connector_execution=McpConnectorWriteAdapter(gateway=gateway),
        tool_catalog=_tool_catalog(),
        now_ms=FakeClockPort(1000).now_ms,
        id_factory=DeterministicUUID(prefix="runtime").next_id,
        signing_secret="stage17-secret",
        service_instance_id="stage17-service",
        checkpoint_database_path=tmp_path / "checkpoints-freebusy.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
        default_tasklist_id_provider=lambda: "task-list-default",
    )

    try:
        state = runtime._initial_state(_start_request())  # noqa: SLF001
        state["request_intent"] = _action_intent(resource="CALENDAR", effect="READ")
        state["request_intent"]["meta"] = {"artifact_id": "intent-1", "revision": 1, "based_on": []}
        routed = runtime._tool_route_subgraph.invoke(state)  # noqa: SLF001
        input_routes = routed["tool_route_plan"]["input_plan"]["input_routes"]
        assert input_routes
        assert {route["resource_type"] for route in input_routes} <= {
            "CALENDAR",
            "CALENDAR_EVENT",
            "CALENDAR_FREEBUSY",
        }
        route_ids = [route["route_id"] for route in input_routes]

        # The FREEBUSY route_ids are only known once Tool Route actually
        # froze the routes, so the queue is populated after that call rather
        # than at runtime construction time.
        llm_runtime._queued.extend(  # noqa: SLF001
            [
                _llm_result(_selection_output()),
                _llm_result(_sufficiency_output("NEEDS_MORE_DATA")),
                _llm_result(_freebusy_plan_query(route_ids)),
                _llm_result(_selection_output()),
                _llm_result(_sufficiency_output("SUFFICIENT")),
            ]
        )

        context = runtime._context_subgraph.invoke(routed)  # noqa: SLF001

        assert context["__target__"] == "work_analysis"
        assert context["retrieval_result"] is not None
        plan_query_calls = [
            call
            for call in llm_runtime.calls
            if getattr(call["prompt_ref"], "prompt_id", None) == "retrieval.plan_query"
        ]
        assert len(plan_query_calls) == 2
        assert gateway.count_calls("query_freebusy") >= 1
    finally:
        runtime.close()
