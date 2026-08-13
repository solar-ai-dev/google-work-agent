"""Graph profile and subgraph integration tests."""

from __future__ import annotations

from tests.integration.langgraph.test_runtime import (
    FIXTURE_ROOT,
    Callable,
    DeterministicUUID,
    FakeClock,
    FakeGoogleGateway,
    GoogleWorkspaceExecutionBackend,
    GraphProfile,
    LangGraphWorkflowRuntime,
    Path,
    ProductFixtureSnapshotLoader,
    WorkflowOutcome,
    _action_required_intent,
    _analysis_output,
    _answer_output,
    _clear_intent,
    _context_result,
    _make_runtime,
    _plan,
    _profile_reason_plan_output,
    _profile_request_source_output,
    _QueuedLLMRuntime,
    _review_output,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _start_request,
    _start_write_request,
    _sufficiency_output,
    _tool_catalog,
    _validated_analysis_result,
    _write_plan_output,
    pytest,
    sqlite_unit_of_work_factory,
    supported_graph_profiles,
)


def test_graph_profile_registry_exposes_three_supported_profiles() -> None:
    assert supported_graph_profiles() == (
        GraphProfile.SINGLE_BASELINE,
        GraphProfile.THREE_STAGE,
        GraphProfile.SIX_ROLE_BASELINE,
    )


def test_langgraph_runtime_reports_distinct_topologies_by_profile(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    six = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-six.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )
    three = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-three.db",
        graph_profile=GraphProfile.THREE_STAGE,
        prompt_manifest_path=manifest_path,
    )
    single = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-single.db",
        graph_profile=GraphProfile.SINGLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        assert six.describe_topology() == (
            "request_understanding",
            "acquisition",
            "context_retriever",
            "work_analysis",
            "planning",
            "review",
        )
        assert three.describe_topology() == ("stage_one", "stage_two", "stage_three")
        assert single.describe_topology() == ("single_workflow",)
        assert six.describe_topology() != three.describe_topology()
        assert single.describe_topology() != three.describe_topology()
    finally:
        six.close()
        three.close()
        single.close()


def test_six_role_runtime_exposes_six_native_agent_subgraphs(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-subgraphs.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        assert tuple(runtime._native_agent_subgraphs) == (  # noqa: SLF001
            "request_understanding",
            "acquisition",
            "context_retriever",
            "work_analysis",
            "planning",
            "review",
        )
        assert len(runtime._native_agent_subgraphs) == 6  # noqa: SLF001
        assert runtime._node_handler("request_understanding") is runtime._request_subgraph  # noqa: SLF001
        assert runtime._node_handler("acquisition") is runtime._acquisition_subgraph  # noqa: SLF001
        assert runtime._node_handler("context_retriever") is runtime._context_subgraph  # noqa: SLF001
        assert runtime._node_handler("work_analysis") is runtime._analysis_subgraph  # noqa: SLF001
        assert runtime._node_handler("planning") is runtime._planning_subgraph  # noqa: SLF001
        assert runtime._node_handler("review") is runtime._review_subgraph  # noqa: SLF001
    finally:
        runtime.close()


def test_native_profile_runtimes_expose_three_and_single_subgraphs(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    three = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-three-subgraphs.db",
        graph_profile=GraphProfile.THREE_STAGE,
        prompt_manifest_path=manifest_path,
    )
    single = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-single-subgraphs.db",
        graph_profile=GraphProfile.SINGLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        assert tuple(three._native_agent_subgraphs) == ("stage_one", "stage_two", "stage_three")  # noqa: SLF001
        assert three._node_handler("stage_one") is three._three_stage_one_subgraph  # noqa: SLF001
        assert three._node_handler("stage_two") is three._three_stage_two_subgraph  # noqa: SLF001
        assert three._node_handler("stage_three") is three._three_stage_review_subgraph  # noqa: SLF001
        assert tuple(single._native_agent_subgraphs) == ("single_workflow",)  # noqa: SLF001
        assert single._node_handler("single_workflow") is single._single_workflow_subgraph  # noqa: SLF001
    finally:
        three.close()
        single.close()


def test_request_subgraph_clears_local_state_and_records_trace_counts(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[_clear_intent()],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-request-subgraph.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        state = runtime._initial_state(_start_request())  # noqa: SLF001
        result = runtime._request_subgraph.invoke(state)  # noqa: SLF001

        assert "__request_agent_local__" not in result
        assert result["__logical_target__"] == "tool_route"
        assert result["__target__"] == "tool_route"
        trace_context = result["trace_context"]
        assert trace_context["agent_invocation_count"] == 1
        assert trace_context["llm_call_count"] == 1
        assert [item["node_name"] for item in trace_context["agent_node_log"]] == [
            "init",
            "classify",
            "finalize",
        ]
    finally:
        runtime.close()


def test_tool_route_subgraph_freezes_plan_before_acquisition(tmp_path: Path) -> None:
    runtime = _make_runtime(
        database_path=_seed_runtime_database(tmp_path),
        llm_payloads=[_clear_intent()],
        gateway=FakeGoogleGateway(
            ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
        ),
        checkpoint_database_path=tmp_path / "checkpoints-tool-route.db",
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
    )

    try:
        understood = runtime._request_subgraph.invoke(  # noqa: SLF001
            runtime._initial_state(_start_request())  # noqa: SLF001
        )
        routed = runtime._tool_route_subgraph.invoke(understood)  # noqa: SLF001

        assert routed["__target__"] == "acquisition"
        assert routed["tool_route_plan"]["schema_version"] == 2
        input_routes = routed["tool_route_plan"]["input_plan"]["input_routes"]
        assert {route["resource_type"] for route in input_routes} == {"TASK", "TASK_LIST"}
        assert "__tool_route_result__" not in routed
    finally:
        runtime.close()


def test_acquisition_subgraph_keeps_single_invocation_id_and_parent_isolation(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    llm_runtime = _QueuedLLMRuntime([[_plan("TASKS", {"task_list_id": "task-list-default"})]])
    runtime = LangGraphWorkflowRuntime(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        llm_runtime=llm_runtime,
        gateway=gateway,
        connector_execution=GoogleWorkspaceExecutionBackend(gateway=gateway),
        tool_catalog=_tool_catalog(),
        now_ms=FakeClock(1000).now_ms,
        id_factory=DeterministicUUID(prefix="runtime").next_id,
        signing_secret="stage17-secret",
        service_instance_id="stage17-service",
        checkpoint_database_path=tmp_path / "checkpoints-acquisition-subgraph.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        state = runtime._initial_state(_start_request())  # noqa: SLF001
        state["request_intent"] = _clear_intent()
        result = runtime._acquisition_subgraph.invoke(state)  # noqa: SLF001

        assert "__request_agent_local__" not in result
        assert "__acquisition_agent_local__" not in result
        assert "__acquisition_planning_output__" not in result
        assert result["__logical_target__"] == "context_retriever"
        assert result["__target__"] == "context_retriever"
        assert gateway.count_calls("list_tasks") == 1
        assert gateway.count_calls("get_task") >= 1
        assert gateway.count_calls("search_gmail_threads") == 0
        assert gateway.count_calls("list_calendar_events") == 0
        assert len(llm_runtime.calls) == 1

        trace_context = result["trace_context"]
        assert trace_context["agent_invocation_count"] == 1
        assert trace_context["llm_call_count"] == 1
        node_log = trace_context["agent_node_log"]
        assert [item["node_name"] for item in node_log] == [
            "init",
            "plan_sources",
            "plan_validate",
            "deterministic_read",
            "result_validate",
            "finalize",
        ]
        invocation_ids = {item["agent_invocation_id"] for item in node_log}
        assert len(invocation_ids) == 1
        assert {item["agent_subgraph_id"] for item in node_log} == {"acquisition"}
    finally:
        runtime.close()


def test_six_role_full_path_records_six_agent_invocations_and_seven_llm_calls(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _clear_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-six-full.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        result = runtime.start(_start_request())
        snapshot_state = runtime._graph.get_state(runtime._config_for_thread("thread-1"))  # noqa: SLF001
        values = snapshot_state.values

        assert result.outcome is WorkflowOutcome.COMPLETED
        trace_context = values["trace_context"]
        assert trace_context["agent_invocation_count"] == 6
        assert trace_context["llm_call_count"] == 7
        init_log = [
            item["agent_subgraph_id"]
            for item in trace_context["agent_node_log"]
            if item["node_name"] == "init"
        ]
        assert init_log == [
            "request_understanding",
            "acquisition",
            "context_retriever",
            "work_analysis",
            "planning",
            "review",
        ]
        invocation_ids = {item["agent_invocation_id"] for item in trace_context["agent_node_log"]}
        assert len(invocation_ids) == 6
    finally:
        runtime.close()


def test_context_subgraph_routes_needs_more_data_back_to_parent_acquisition(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("NEEDS_MORE_DATA"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-context-route.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        state = runtime._initial_state(_start_request())  # noqa: SLF001
        state["request_intent"] = _clear_intent()
        acquired = runtime._acquisition_subgraph.invoke(state)  # noqa: SLF001
        routed = runtime._context_subgraph.invoke(acquired)  # noqa: SLF001

        assert routed["__logical_target__"] == "acquisition"
        assert routed["__target__"] == "acquisition"
        assert "__context_agent_local__" not in routed
    finally:
        runtime.close()


def test_agent_subgraphs_route_by_logical_target_without_direct_peer_invocation(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _clear_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("NEEDS_MORE_DATA"),
            _review_output(
                "REVISE",
                issues=[
                    {
                        "schema_version": 2,
                        "issue_id": "issue-1",
                        "kind": "MISSING_GOAL_COVERAGE",
                        "message": "Need a revision.",
                        "affected_action_ids": [],
                        "affected_field_paths": ["$.answer"],
                        "evidence_refs": ["evidence-1"],
                        "resource_refs": ["task:task-followup"],
                        "reason_codes": ["EVIDENCE_SUPPORTED"],
                    }
                ],
            ),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-no-direct-peer.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    peer_invocations: list[str] = []

    def _forbid_peer_invoke(peer_name: str) -> Callable[..., object]:
        def _raise(*args: object, **kwargs: object) -> object:
            peer_invocations.append(peer_name)
            raise AssertionError(f"unexpected direct peer invoke: {peer_name}")

        return _raise

    original_acquisition_invoke = runtime._acquisition_subgraph.invoke  # noqa: SLF001
    original_context_invoke = runtime._context_subgraph.invoke  # noqa: SLF001
    original_planning_invoke = runtime._planning_subgraph.invoke  # noqa: SLF001

    try:
        runtime._acquisition_subgraph.invoke = _forbid_peer_invoke("acquisition")  # noqa: SLF001
        request_state = runtime._initial_state(_start_request())  # noqa: SLF001
        request_result = runtime._request_subgraph.invoke(request_state)  # noqa: SLF001
        assert request_result["__target__"] == "tool_route"

        runtime._acquisition_subgraph.invoke = original_acquisition_invoke  # noqa: SLF001
        runtime._context_subgraph.invoke = _forbid_peer_invoke("context_retriever")  # noqa: SLF001
        acquisition_state = runtime._initial_state(_start_request())  # noqa: SLF001
        acquisition_state["request_intent"] = _clear_intent()
        acquisition_result = runtime._acquisition_subgraph.invoke(acquisition_state)  # noqa: SLF001
        assert acquisition_result["__target__"] == "context_retriever"

        runtime._context_subgraph.invoke = original_context_invoke  # noqa: SLF001
        runtime._acquisition_subgraph.invoke = _forbid_peer_invoke("acquisition")  # noqa: SLF001
        routed = runtime._context_subgraph.invoke(acquisition_result)  # noqa: SLF001
        assert routed["__target__"] == "acquisition"

        runtime._acquisition_subgraph.invoke = original_acquisition_invoke  # noqa: SLF001
        runtime._planning_subgraph.invoke = _forbid_peer_invoke("planning")  # noqa: SLF001
        review_state = runtime._initial_state(_start_request())  # noqa: SLF001
        review_state["request_intent"] = _clear_intent()
        review_state["context_result"] = _context_result()
        review_state["analysis_result"] = _validated_analysis_result()
        review_state["answer_draft"] = _answer_output()
        review_result = runtime._review_subgraph.invoke(review_state)  # noqa: SLF001
        assert review_result["__target__"] == "planning"

        assert peer_invocations == []
    finally:
        runtime._acquisition_subgraph.invoke = original_acquisition_invoke  # noqa: SLF001
        runtime._context_subgraph.invoke = original_context_invoke  # noqa: SLF001
        runtime._planning_subgraph.invoke = original_planning_invoke  # noqa: SLF001
        runtime.close()


def test_review_subgraph_routes_revise_and_retrieve_more_through_parent(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    issue = {
        "schema_version": 2,
        "issue_id": "issue-1",
        "kind": "MISSING_GOAL_COVERAGE",
        "message": "Need a revision.",
        "affected_action_ids": [],
        "affected_field_paths": ["$.answer"],
        "evidence_refs": ["evidence-1"],
        "resource_refs": ["task:task-followup"],
        "reason_codes": ["EVIDENCE_SUPPORTED"],
    }
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _review_output("REVISE", issues=[issue]),
            _review_output("RETRIEVE_MORE", issues=[issue]),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-review-route.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        base_state = runtime._initial_state(_start_request())  # noqa: SLF001
        base_state["request_intent"] = _clear_intent()
        base_state["context_result"] = _context_result()
        base_state["analysis_result"] = _validated_analysis_result()
        base_state["answer_draft"] = _answer_output()

        revise_state = runtime._review_subgraph.invoke(dict(base_state))  # noqa: SLF001
        assert revise_state["__logical_target__"] == "planning"
        assert revise_state["__target__"] == "planning"

        retrieve_state = runtime._review_subgraph.invoke(dict(base_state))  # noqa: SLF001
        assert retrieve_state["__logical_target__"] == "acquisition"
        assert retrieve_state["__target__"] == "acquisition"
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "graph_profile",
    [
        GraphProfile.SIX_ROLE_BASELINE,
        GraphProfile.SINGLE_BASELINE,
        GraphProfile.THREE_STAGE,
    ],
)
def test_agent_subgraphs_do_not_issue_google_writes_before_approval(
    tmp_path: Path,
    graph_profile: GraphProfile,
) -> None:
    root = tmp_path / graph_profile.value.lower()
    root.mkdir()
    manifest_path = _runtime_active_manifest_path(root)
    database_path = _seed_runtime_database(root)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    llm_payloads = (
        [
            _action_required_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _write_plan_output(),
            _review_output("PASS"),
        ]
        if graph_profile is GraphProfile.SIX_ROLE_BASELINE
        else [
            _profile_request_source_output(),
            _profile_reason_plan_output("PLAN_READY"),
            _review_output("PASS"),
        ]
    )
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=llm_payloads,
        gateway=gateway,
        checkpoint_database_path=root / "checkpoints-no-write.db",
        graph_profile=graph_profile,
        prompt_manifest_path=manifest_path,
    )

    try:
        started = runtime.start(_start_write_request())
        assert started.outcome is WorkflowOutcome.ACCEPTED
        assert gateway.count_calls("create_task") == 0
        assert gateway.count_calls("update_task") == 0
        assert gateway.count_calls("create_calendar_event") == 0
        assert gateway.count_calls("update_calendar_event") == 0
        assert gateway.count_calls("create_gmail_draft") == 0
        assert gateway.count_calls("update_gmail_draft") == 0
    finally:
        runtime.close()
