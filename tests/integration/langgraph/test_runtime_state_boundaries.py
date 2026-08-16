"""Typed state and routing boundary integration tests."""

from __future__ import annotations

from typing import Literal

from tests.integration.langgraph.test_runtime import (
    _ACTION_REQUIRED_SEMANTIC_CASES,
    _ANSWER_ONLY_SEMANTIC_CASES,
    _PROFILE_CANDIDATE_PROMPT_IDS,
    _RUNTIME_ACTIVE_PROMPT_IDS,
    FIXTURE_ROOT,
    DeterministicUUID,
    FakeClock,
    FakeGoogleGateway,
    GoogleGatewayFault,
    GoogleGatewayFaultKind,
    GoogleWorkspaceExecutionBackend,
    GraphProfile,
    InactivePromptArtifactError,
    LangGraphWorkflowRuntime,
    Path,
    ProductFixtureSnapshotLoader,
    _action_required_intent,
    _ambiguous_intent,
    _analysis_output,
    _answer_output,
    _clear_intent,
    _context_result,
    _make_runtime,
    _plan,
    _planning_mode_runtime,
    _QueuedLLMRuntime,
    _review_output,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _start_request,
    _sufficiency_output,
    _tool_catalog,
    pytest,
    sqlite_unit_of_work_factory,
)
from tests.support.prompt_manifests import write_manifest_with_legacy_profile_slots

from google_work_agent.adapters.langgraph.graph_state import CONTEXT_RAG_CANDIDATES_KEY


def test_single_and_three_stage_runtimes_still_reject_own_draft_prompts(
    tmp_path: Path,
) -> None:
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    manifest_path = write_manifest_with_legacy_profile_slots(
        tmp_path,
        legacy_prompt_ids=_PROFILE_CANDIDATE_PROMPT_IDS,
        active_prompt_ids=_RUNTIME_ACTIVE_PROMPT_IDS,
        draft_prompt_ids=_PROFILE_CANDIDATE_PROMPT_IDS,
    )

    with pytest.raises(InactivePromptArtifactError, match="profile.single.request_source.initial"):
        _make_runtime(
            database_path=database_path,
            llm_payloads=[],
            gateway=FakeGoogleGateway(snapshot),
            checkpoint_database_path=tmp_path / "checkpoints-single-draft.db",
            prompt_manifest_path=manifest_path,
            graph_profile=GraphProfile.SINGLE_BASELINE,
        )

    with pytest.raises(InactivePromptArtifactError, match="profile.three.stage1.initial"):
        _make_runtime(
            database_path=database_path,
            llm_payloads=[],
            gateway=FakeGoogleGateway(snapshot),
            checkpoint_database_path=tmp_path / "checkpoints-three-draft.db",
            prompt_manifest_path=manifest_path,
            graph_profile=GraphProfile.THREE_STAGE,
        )


@pytest.mark.parametrize(
    ("case_id", "request_text"),
    _ANSWER_ONLY_SEMANTIC_CASES,
    ids=[case_id for case_id, _ in _ANSWER_ONLY_SEMANTIC_CASES],
)
def test_planning_mode_answer_only_semantic_cases_ignore_request_text(
    tmp_path: Path, case_id: str, request_text: str
) -> None:
    del case_id
    runtime = _planning_mode_runtime(tmp_path)
    intent = _clear_intent()
    assert runtime._planning_mode_from_request_intent(intent) == "answer_only"
    runtime.close()


@pytest.mark.parametrize(
    ("case_id", "request_text"),
    _ACTION_REQUIRED_SEMANTIC_CASES,
    ids=[case_id for case_id, _ in _ACTION_REQUIRED_SEMANTIC_CASES],
)
def test_planning_mode_action_required_semantic_cases_ignore_request_text(
    tmp_path: Path, case_id: str, request_text: str
) -> None:
    del case_id
    runtime = _planning_mode_runtime(tmp_path)
    intent = _action_required_intent()
    assert runtime._planning_mode_from_request_intent(intent) == "draft_plan"
    runtime.close()


def test_planning_mode_falls_back_to_answer_only_when_no_write_effect_hint_present(
    tmp_path: Path,
) -> None:
    """A classify output with no write effect hint (requested_effect_hints
    has no CREATE/UPDATE/SEND/DELETE) never fabricates an Action Plan the
    user did not ask for -- it falls back to answer_only rather than
    guessing."""
    runtime = _planning_mode_runtime(tmp_path)
    intent = _clear_intent()
    intent["requested_effect_hints"] = []
    assert runtime._planning_mode_from_request_intent(intent) == "answer_only"
    runtime.close()


@pytest.mark.parametrize(
    ("source", "constraints", "expected_operation"),
    [
        ("GMAIL", {}, "search_gmail_threads"),
        ("CALENDAR", {"calendar_id": "calendar-primary"}, "list_calendar_events"),
        ("TASKS", {"task_list_id": "task-list-default"}, "list_tasks"),
    ],
)
def test_edge_request_to_acquisition_to_context_preserves_typed_state(
    tmp_path: Path,
    source: Literal["GMAIL", "CALENDAR", "TASKS"],
    constraints: dict[str, object],
    expected_operation: str,
) -> None:
    root = tmp_path / source.lower()
    root.mkdir()
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    intent = _clear_intent()
    runtime = _make_runtime(
        database_path=_seed_runtime_database(root),
        llm_payloads=[intent, [_plan(source, constraints)]],
        gateway=gateway,
        checkpoint_database_path=root / "checkpoints.db",
        prompt_manifest_path=_runtime_active_manifest_path(root),
    )

    try:
        initial = runtime._initial_state(_start_request())  # noqa: SLF001
        understood = runtime._request_subgraph.invoke(initial)  # noqa: SLF001
        intent_without_meta = {
            key: value for key, value in understood["request_intent"].items() if key != "meta"
        }
        assert intent_without_meta == intent
        assert understood["request_intent"]["meta"]["revision"] == 1
        assert understood["__target__"] == "tool_route"

        acquired = runtime._acquisition_subgraph.invoke(understood)  # noqa: SLF001
        assert acquired["__target__"] == "context_retriever"
        assert acquired["source_fetch_plans"][0]["source"] == source
        assert acquired["acquisition_result"]["status"] in {"COMPLETE", "PARTIAL"}
        assert gateway.count_calls(expected_operation) >= 1
    finally:
        runtime.close()


def test_edge_answer_only_no_fetch_skips_google_and_builds_typed_result(
    tmp_path: Path,
) -> None:
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    runtime = _make_runtime(
        database_path=_seed_runtime_database(tmp_path),
        llm_payloads=[_clear_intent(), []],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-no-fetch-edge.db",
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
    )

    try:
        understood = runtime._request_subgraph.invoke(  # noqa: SLF001
            runtime._initial_state(_start_request())  # noqa: SLF001
        )
        acquired = runtime._acquisition_subgraph.invoke(understood)  # noqa: SLF001
        assert acquired["__target__"] == "context_retriever"
        assert acquired["source_fetch_plans"] == []
        assert acquired["acquisition_result"]["status"] == "COMPLETE"
        assert acquired["acquisition_result"]["source_summaries"] == []
        assert gateway.call_log == []
    finally:
        runtime.close()


def test_edge_acquisition_failure_never_routes_to_context_as_success(tmp_path: Path) -> None:
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    gateway.queue_fault(
        operation="list_tasks",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.HTTP_500),
    )
    runtime = _make_runtime(
        database_path=_seed_runtime_database(tmp_path),
        llm_payloads=[[_plan("TASKS", {"task_list_id": "task-list-default"})]],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-acquisition-failure-edge.db",
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
    )

    try:
        state = runtime._initial_state(_start_request())  # noqa: SLF001
        state["request_intent"] = _clear_intent()
        result = runtime._acquisition_subgraph.invoke(state)  # noqa: SLF001
        assert result["acquisition_result"]["status"] == "FAILED"
        assert result["__target__"] == "finalize"
        assert result["workflow_phase"] == "FINALIZE"
        assert result["context_result"] is None
    finally:
        runtime.close()


def test_edge_partial_acquisition_preserves_result_and_routes_to_context(tmp_path: Path) -> None:
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    gateway.queue_fault(
        operation="search_gmail_threads",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.HTTP_500),
    )
    runtime = _make_runtime(
        database_path=_seed_runtime_database(tmp_path),
        llm_payloads=[
            [
                _plan("TASKS", {"task_list_id": "task-list-default"}),
                _plan("GMAIL", {}),
            ]
        ],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-acquisition-partial-edge.db",
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
    )

    try:
        state = runtime._initial_state(_start_request())  # noqa: SLF001
        state["request_intent"] = _clear_intent()
        result = runtime._acquisition_subgraph.invoke(state)  # noqa: SLF001
        assert result["acquisition_result"]["status"] == "PARTIAL"
        assert result["__target__"] == "context_retriever"
        assert len(result["acquisition_result"]["source_summaries"]) == 2
    finally:
        runtime.close()


def test_edge_required_confirmation_stops_before_acquisition(tmp_path: Path) -> None:
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    runtime = _make_runtime(
        database_path=_seed_runtime_database(tmp_path),
        llm_payloads=[_ambiguous_intent()],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-confirm-edge.db",
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
    )

    try:
        result = runtime._request_subgraph.invoke(  # noqa: SLF001
            runtime._initial_state(_start_request())  # noqa: SLF001
        )
        assert result["__target__"] == "waiting_confirmation"
        assert result["workflow_phase"] == "WAITING_CONFIRMATION"
        assert result["user_interrupt"]["origin_target"] == "request_understanding.classify"
        assert gateway.call_log == []
    finally:
        runtime.close()


def test_chain_context_analysis_planning_review_preserves_typed_outputs(
    tmp_path: Path,
) -> None:
    llm_runtime = _QueuedLLMRuntime(
        [
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
            _review_output("PASS"),
        ]
    )
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    runtime = LangGraphWorkflowRuntime(
        unit_of_work_factory=sqlite_unit_of_work_factory(_seed_runtime_database(tmp_path)),
        llm_runtime=llm_runtime,
        gateway=gateway,
        connector_execution=GoogleWorkspaceExecutionBackend(gateway=gateway),
        tool_catalog=_tool_catalog(),
        now_ms=FakeClock(1000).now_ms,
        id_factory=DeterministicUUID(prefix="edge").next_id,
        signing_secret="edge-secret",
        service_instance_id="edge-service",
        checkpoint_database_path=tmp_path / "checkpoints-chain-b.db",
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
    )

    try:
        state = runtime._initial_state(_start_request())  # noqa: SLF001
        state["request_intent"] = _clear_intent()
        state["request_intent"]["meta"] = {"artifact_id": "intent-1", "revision": 1, "based_on": []}
        routed = runtime._tool_route_subgraph.invoke(state)  # noqa: SLF001
        acquired = runtime._acquisition_subgraph.invoke(routed)  # noqa: SLF001
        context = runtime._context_subgraph.invoke(acquired)  # noqa: SLF001
        assert context["__target__"] == "work_analysis"
        assert context["context_result"]["evidence_drafts"][0]["evidence_id"] == "evidence-seg-2"
        assert CONTEXT_RAG_CANDIDATES_KEY not in context

        analysis = runtime._analysis_subgraph.invoke(context)  # noqa: SLF001
        assert analysis["__target__"] == "planning"
        assert analysis["analysis_result"]["findings"][0]["finding_id"] == "finding-1"

        planned = runtime._planning_subgraph.invoke(analysis)  # noqa: SLF001
        assert planned["__target__"] == "review"
        assert planned["answer_draft"]["evidence_refs"] == ["evidence-seg-2"]

        reviewed = runtime._review_subgraph.invoke(planned)  # noqa: SLF001
        assert reviewed["__target__"] == "finalize"
        assert reviewed["plan_review"]["status"] == "PASS"
        planning_input = llm_runtime.calls[5]["prompt_input"]
        assert isinstance(planning_input, dict)
        assert planning_input["analysis_result"]["findings"][0]["finding_id"] == "finding-1"
    finally:
        runtime.close()


def test_edge_analysis_confirmation_never_enters_planning(tmp_path: Path) -> None:
    output = _analysis_output()
    output["status"] = "NEEDS_CONFIRMATION"
    output["confirmation"] = {
        "reason_code": "ANALYSIS_RELATIONSHIP_AMBIGUITY",
        "question": "Which task should be primary?",
    }
    runtime = _make_runtime(
        database_path=_seed_runtime_database(tmp_path),
        llm_payloads=[output],
        gateway=FakeGoogleGateway(
            ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
        ),
        checkpoint_database_path=tmp_path / "checkpoints-analysis-confirm-edge.db",
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
    )

    try:
        state = runtime._initial_state(_start_request())  # noqa: SLF001
        state["request_intent"] = _clear_intent()
        context_result = _context_result()
        state["context_result"] = context_result
        state["retrieval_result"] = {
            "schema_version": 1,
            "meta": {"artifact_id": "retrieval-1", "revision": 1, "based_on": []},
            "coverage": "SUFFICIENT",
            "context_bundle_ref": None,
            "evidence_refs": ["evidence-seg-2"],
            "selected_segment_ids": ["seg-2"],
            "source_resource_refs": ["task:task-followup"],
            "source_statuses": [],
            "missing_information": [],
            "retrieval_rounds": 1,
        }
        runtime._evidence_store.put(  # noqa: SLF001
            run_id=state["run_id"], evidence_drafts=context_result["evidence_drafts"]
        )
        result = runtime._analysis_subgraph.invoke(state)  # noqa: SLF001
        assert result["__target__"] == "waiting_confirmation"
        assert result["analysis_result"]["status"] == "NEEDS_CONFIRMATION"
        assert result["plan_draft"] is None
        assert result["answer_draft"] is None
    finally:
        runtime.close()
