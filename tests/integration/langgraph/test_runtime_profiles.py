"""Graph profile and subgraph integration tests."""

from __future__ import annotations

from tests.integration.langgraph.test_runtime import (
    FIXTURE_ROOT,
    Callable,
    FakeGoogleGateway,
    GraphProfile,
    Path,
    ProductFixtureSnapshotLoader,
    WorkflowOutcome,
    _action_required_intent,
    _analysis_output,
    _answer_output,
    _clear_intent,
    _context_result,
    _evidence_drafts_seg_2,
    _make_runtime,
    _make_runtime_with_llm,
    _plan,
    _profile_reason_plan_output,
    _profile_request_source_output,
    _QueuedLLMRuntime,
    _retrieval_result,
    _review_output,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _start_request,
    _start_write_request,
    _sufficiency_output,
    _validated_analysis_result,
    _write_plan_output,
    pytest,
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
    """SIX_ROLE_BASELINE's active agent set is request_understanding,
    context_retriever, work_analysis, planning, review -- ``acquisition``
    stays a registered node (resolvable via ``_node_handler``, used by other
    profiles/legacy paths) but is not part of this profile's own topology
    since Retrieval V2's context_retriever subgraph replaced it here."""
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
            "tool_route",
            "context_retriever",
            "work_analysis",
            "planning",
            "review",
        )
        assert len(runtime._native_agent_subgraphs) == 6  # noqa: SLF001
        assert runtime._node_handler("request_understanding") is runtime._request_subgraph  # noqa: SLF001
        assert runtime._node_handler("tool_route") is runtime._tool_route_subgraph  # noqa: SLF001
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
        assert trace_context["llm_call_count"] == 2
        assert [item["node_name"] for item in trace_context["agent_node_log"]] == [
            "identify_goal",
            "detect_ambiguity",
            "finalize_intent",
        ]
    finally:
        runtime.close()


def test_tool_route_subgraph_freezes_plan_before_context_retriever(tmp_path: Path) -> None:
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

        assert routed["__target__"] == "context_retriever"
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
    database_path = _seed_runtime_database(tmp_path, status="ANALYZING")
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    llm_runtime = _QueuedLLMRuntime([[_plan("TASKS", {"task_list_id": "task-list-default"})]])
    runtime = _make_runtime_with_llm(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
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
    """SIX_ROLE_BASELINE's active agent set is request_understanding,
    tool_route, context_retriever, work_analysis, planning, review.
    ``acquisition`` is not
    wired into this profile's topology (Retrieval V2's context_retriever
    subgraph replaced it; see ``_native_subgraphs_for_profile``).

    Uses an ACTION (write) plan rather than an ANSWER_ONLY one so Review is
    actually reached: canonical_response_runtime.
    canonicalize_answer_only_decision() deterministically routes
    Planning-ANSWER_ONLY straight to Response Synthesis instead of Review
    (docs/design/06-agent-workflow.md: "Planning ANSWER_ONLY -> Response
    Synthesis"), which would make this "full 5-agent path including
    Review" fixture silently stop covering Review.
    """
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _action_required_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _write_plan_output(),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-six-full.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        result = runtime.start(_start_write_request())
        snapshot_state = runtime._graph.get_state(runtime._config_for_thread("thread-1"))  # noqa: SLF001
        values = snapshot_state.values

        # ACTION plans stop at WAITING_APPROVAL after a PASS Review, not
        # COMPLETED -- Review having run (and rendered a real decision) is
        # what this test is proving, not full write execution.
        assert result.outcome is WorkflowOutcome.ACCEPTED
        trace_context = values["trace_context"]
        assert trace_context["agent_invocation_count"] == 6
        assert trace_context["llm_call_count"] == 8
        invocation_log: list[str] = []
        seen_invocation_ids: set[str] = set()
        for item in trace_context["agent_node_log"]:
            invocation_id = item["agent_invocation_id"]
            if invocation_id in seen_invocation_ids:
                continue
            seen_invocation_ids.add(invocation_id)
            invocation_log.append(item["agent_subgraph_id"])
        assert invocation_log == [
            "request_understanding",
            "tool_route",
            "context_retriever",
            "work_analysis",
            "planning",
            "review",
        ]
        invocation_ids = {item["agent_invocation_id"] for item in trace_context["agent_node_log"]}
        assert len(invocation_ids) == 6
    finally:
        runtime.close()


def test_retrieval_rejects_execution_without_a_frozen_tool_route(
    tmp_path: Path,
) -> None:
    """Retrieval's own local-loop NEEDS_MORE_DATA (no frozen tool_route_plan
    -- e.g. the compatibility entry point that already holds an
    acquisition_result) stays on the pre-Q2-HANDOFF
    ``_route_additional_acquisition`` path, unchanged, targeting
    ``SupervisorTarget.SOURCE_PLANNING``. SIX_ROLE_BASELINE's own route
    translation table (route_translation.py) maps SOURCE_PLANNING/
    API_ACQUISITION to the "context_retriever" node for this profile --
    Retrieval V2 replaced the standalone "acquisition" node here, so this
    is a same-subgraph re-entry, not a peer handoff. This is deliberately
    distinct from WorkAnalysis/Review's NEEDS_MORE_DATA/RETRIEVE_MORE, which
    goes through ``_route_retrieval_required`` (see
    test_review_subgraph_routes_revise_and_retrieve_more_through_parent)."""
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path, status="ANALYZING")
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
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
        # Hand-built in the same reference space _context_result() uses
        # (task:task-followup -> seg-2), bypassing the legacy acquisition
        # subgraph's own LLM-driven plan_sources node -- this test is about
        # context_retriever's routing decision, not acquisition's planning.
        state["acquisition_result"] = {
            "schema_version": 1,
            "status": "COMPLETE",
            "resource_handles": ["task:task-billing", "task:task-followup"],
            "source_summaries": [
                {
                    "schema_version": 1,
                    "source": "TASKS",
                    "status": "COMPLETE",
                    "resources": [
                        {
                            "resource_handle": "task:task-billing",
                            "resource_type": "task",
                            "resource_id": "task-billing",
                            "parent_id": "task-list-default",
                            "version": "1",
                            "payload": {"title": "Pay contractor invoice"},
                        },
                        {
                            "resource_handle": "task:task-followup",
                            "resource_type": "task",
                            "resource_id": "task-followup",
                            "parent_id": "task-list-default",
                            "version": "1",
                            "payload": {"title": "Reply to project sync"},
                        },
                    ],
                }
            ],
            "missing_slots": [],
            "remaining_budget": {"sources": 3, "pages": 3, "candidates": 60, "details": 30},
        }
        with pytest.raises(ValueError, match="tool_route_plan"):
            runtime._context_subgraph.invoke(state)  # noqa: SLF001
    finally:
        runtime.close()


def test_agent_subgraphs_route_by_logical_target_without_direct_peer_invocation(
    tmp_path: Path,
) -> None:
    """SIX_ROLE_BASELINE's real topology is request_understanding ->
    tool_route -> context_retriever -> work_analysis -> planning -> review
    (``acquisition`` is a registered node but not part of this profile's own
    edges -- see test_tool_route_subgraph_freezes_plan_before_context_retriever
    and test_six_role_runtime_exposes_six_native_agent_subgraphs). Each
    stage below calls exactly one subgraph directly and asserts it only ever
    hands off via ``__target__`` -- never by invoking the next subgraph's
    ``.invoke`` itself."""
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _clear_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
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
                        "evidence_refs": ["evidence-seg-2"],
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

    original_tool_route_invoke = runtime._tool_route_subgraph.invoke  # noqa: SLF001
    original_context_invoke = runtime._context_subgraph.invoke  # noqa: SLF001
    original_analysis_invoke = runtime._analysis_subgraph.invoke  # noqa: SLF001
    original_planning_invoke = runtime._planning_subgraph.invoke  # noqa: SLF001

    try:
        runtime._tool_route_subgraph.invoke = _forbid_peer_invoke("tool_route")  # noqa: SLF001
        request_state = runtime._initial_state(_start_request())  # noqa: SLF001
        request_result = runtime._request_subgraph.invoke(request_state)  # noqa: SLF001
        assert request_result["__target__"] == "tool_route"

        runtime._tool_route_subgraph.invoke = original_tool_route_invoke  # noqa: SLF001
        runtime._context_subgraph.invoke = _forbid_peer_invoke("context_retriever")  # noqa: SLF001
        tool_route_state = runtime._initial_state(_start_request())  # noqa: SLF001
        tool_route_state["request_intent"] = _clear_intent()
        tool_route_state["request_intent"]["meta"] = {
            "artifact_id": "intent-1",
            "revision": 1,
            "based_on": [],
        }
        routed = runtime._tool_route_subgraph.invoke(tool_route_state)  # noqa: SLF001
        assert routed["__target__"] == "context_retriever"

        runtime._context_subgraph.invoke = original_context_invoke  # noqa: SLF001
        runtime._analysis_subgraph.invoke = _forbid_peer_invoke("work_analysis")  # noqa: SLF001
        context = runtime._context_subgraph.invoke(routed)  # noqa: SLF001
        assert context["__target__"] == "work_analysis"

        runtime._analysis_subgraph.invoke = original_analysis_invoke  # noqa: SLF001
        runtime._planning_subgraph.invoke = _forbid_peer_invoke("planning")  # noqa: SLF001
        # The context_retriever stage above already materialized its stable
        # evidence reference into this run's RunScopedEvidenceStore -- no
        # second ``put`` needed (and a conflicting duplicate ``put`` would
        # fail-closed by design).
        review_state = runtime._initial_state(_start_request())  # noqa: SLF001
        review_state["request_intent"] = _clear_intent()
        review_state["retrieval_result"] = context["retrieval_result"]
        evidence_ref = context["retrieval_result"]["evidence_refs"][0]
        segment_ref = context["retrieval_result"]["selected_segment_ids"][0]
        analysis_result = _validated_analysis_result()
        analysis_result["evidence_refs"] = [evidence_ref]
        analysis_result["segment_refs"][0]["segment_id"] = segment_ref
        analysis_result["findings"][0]["evidence_refs"] = [evidence_ref]
        analysis_result["findings"][0]["segment_refs"] = [segment_ref]
        answer_draft = _answer_output()
        answer_draft["evidence_refs"] = [evidence_ref]
        review_state["analysis_result"] = analysis_result
        review_state["answer_draft"] = answer_draft
        review_result = runtime._review_subgraph.invoke(review_state)  # noqa: SLF001
        assert review_result["__target__"] == "planning"

        assert peer_invocations == []
    finally:
        runtime._tool_route_subgraph.invoke = original_tool_route_invoke  # noqa: SLF001
        runtime._context_subgraph.invoke = original_context_invoke  # noqa: SLF001
        runtime._analysis_subgraph.invoke = original_analysis_invoke  # noqa: SLF001
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
        "evidence_refs": ["evidence-seg-2"],
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
        runtime._evidence_store.put(  # noqa: SLF001
            run_id="run-1", evidence_drafts=_evidence_drafts_seg_2()
        )
        base_state = runtime._initial_state(_start_request())  # noqa: SLF001
        base_state["request_intent"] = _clear_intent()
        base_state["context_result"] = _context_result()
        base_state["retrieval_result"] = _retrieval_result()
        base_state["analysis_result"] = _validated_analysis_result()
        base_state["answer_draft"] = _answer_output()

        revise_state = runtime._review_subgraph.invoke(dict(base_state))  # noqa: SLF001
        assert revise_state["__logical_target__"] == "planning"
        assert revise_state["__target__"] == "planning"

        # This hand-built base_state never froze a tool_route_plan, so
        # _route_retrieval_required's executability guard fails closed to
        # Tool Route (supervisor.py) rather than re-entering Retrieval with
        # no frozen input route to retry within.
        retrieve_state = runtime._review_subgraph.invoke(dict(base_state))  # noqa: SLF001
        assert retrieve_state["__logical_target__"] == "tool_route"
        assert retrieve_state["__target__"] == "tool_route"
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
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _write_plan_output(),
            _review_output("PASS"),
        ]
        if graph_profile is GraphProfile.SIX_ROLE_BASELINE
        else [
            _profile_request_source_output(request_intent=_action_required_intent()),
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
