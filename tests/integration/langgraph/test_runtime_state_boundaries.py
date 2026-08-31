"""Typed state and routing boundary integration tests."""

from __future__ import annotations

from tests.integration.langgraph.test_runtime import (
    _ACTION_REQUIRED_SEMANTIC_CASES,
    _ANSWER_ONLY_SEMANTIC_CASES,
    _PROFILE_CANDIDATE_PROMPT_IDS,
    _RUNTIME_ACTIVE_PROMPT_IDS,
    FIXTURE_ROOT,
    FakeGoogleGateway,
    GraphProfile,
    Path,
    ProductFixtureSnapshotLoader,
    _ambiguous_intent,
    _analysis_output,
    _answer_output,
    _clear_intent,
    _make_runtime,
    _make_runtime_with_llm,
    _QueuedLLMRuntime,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _start_request,
    _sufficiency_output,
    pytest,
)
from tests.support.canonical_workflow_runtime import start_with_admission
from tests.support.checkpoint import sqlite_checkpoint
from tests.support.prompt_manifests import write_manifest_with_legacy_profile_slots

from google_work_agent.adapters.langgraph.main.state import CONTEXT_RAG_CANDIDATES_KEY


def test_single_and_three_stage_runtimes_never_select_legacy_profile_prompts(
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

    runtimes = [
        _make_runtime(
            database_path=database_path,
            llm_payloads=[],
            gateway=FakeGoogleGateway(snapshot),
            checkpoint_port=sqlite_checkpoint(tmp_path / "checkpoints-single-draft.db"),
            prompt_manifest_path=manifest_path,
            graph_profile=GraphProfile.SINGLE_BASELINE,
        ),
        _make_runtime(
            database_path=database_path,
            llm_payloads=[],
            gateway=FakeGoogleGateway(snapshot),
            checkpoint_port=sqlite_checkpoint(tmp_path / "checkpoints-three-draft.db"),
            prompt_manifest_path=manifest_path,
            graph_profile=GraphProfile.THREE_STAGE,
        ),
    ]
    try:
        assert [runtime.graph_profile() for runtime in runtimes] == [
            GraphProfile.SINGLE_BASELINE,
            GraphProfile.THREE_STAGE,
        ]
    finally:
        for runtime in runtimes:
            runtime.close()


@pytest.mark.parametrize(
    ("case_id", "request_text"),
    _ANSWER_ONLY_SEMANTIC_CASES,
    ids=[case_id for case_id, _ in _ANSWER_ONLY_SEMANTIC_CASES],
)
def test_planning_mode_answer_only_semantic_cases_ignore_request_text(
    tmp_path: Path, case_id: str, request_text: str
) -> None:
    del case_id
    from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
        planning_answer_path_selected,
    )

    assert planning_answer_path_selected(
        {"tool_route_plan": {"output_plan": {"output_mode": "ANSWER"}}}
    )


@pytest.mark.parametrize(
    ("case_id", "request_text"),
    _ACTION_REQUIRED_SEMANTIC_CASES,
    ids=[case_id for case_id, _ in _ACTION_REQUIRED_SEMANTIC_CASES],
)
def test_planning_mode_action_required_semantic_cases_ignore_request_text(
    tmp_path: Path, case_id: str, request_text: str
) -> None:
    del case_id
    from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
        planning_answer_path_selected,
    )

    assert not planning_answer_path_selected(
        {"tool_route_plan": {"output_plan": {"output_mode": "ACTION"}}}
    )


def test_action_route_with_not_required_analysis_finishes_as_answer_without_route_reselection(
    tmp_path: Path,
) -> None:
    """A classify output with no write effect hint (requested_effect_hints
    has no CREATE/UPDATE/SEND/DELETE) never fabricates an Action Plan the
    user did not ask for -- it falls back to answer_only rather than
    guessing."""
    from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
        planning_answer_path_selected,
    )

    assert planning_answer_path_selected(
        {
            "tool_route_plan": {"output_plan": {"output_mode": "ACTION"}},
            "work_analysis_result": {"action_necessity": "NOT_REQUIRED"},
        }
    )


def test_edge_required_confirmation_stops_before_acquisition(tmp_path: Path) -> None:
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    database_path = _seed_runtime_database(tmp_path)
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[_ambiguous_intent()],
        gateway=gateway,
        checkpoint_port=sqlite_checkpoint(database_path),
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
    )

    try:
        result = start_with_admission(runtime, database_path, _start_request())
        assert result.payload["user_interrupt"]["origin_target"] == "request.detect_ambiguity"
        snapshot = runtime._graph.get_state(
            runtime._config_for_thread("thread-1"),
            subgraphs=True,
        )
        assert snapshot.next == ("request_understanding",)
        assert snapshot.tasks[0].state.next == ("finalize_intent",)
        assert snapshot.tasks[0].state.values["workflow_phase"] == "WAITING_CONFIRMATION"
        assert gateway.call_log == []
    finally:
        runtime.close()


def test_chain_context_analysis_planning_answer_preserves_typed_outputs(
    tmp_path: Path,
) -> None:
    llm_runtime = _QueuedLLMRuntime(
        [
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
        ]
    )
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    runtime = _make_runtime_with_llm(
        database_path=_seed_runtime_database(tmp_path, status="ANALYZING"),
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_port=sqlite_checkpoint(tmp_path / "checkpoints-chain-b.db"),
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
        id_prefix="edge",
    )

    try:
        state = runtime._initial_state(_start_request())
        request_intent = _clear_intent()
        request_intent["meta"] = {"artifact_id": "intent-1", "revision": 1, "based_on": []}
        state["request_intent"] = request_intent
        routed = runtime._tool_route_subgraph.invoke(state)
        context = runtime._context_subgraph.invoke(routed)
        assert context["__target__"] == "work_analysis"
        evidence_ref = context["retrieval_result"]["evidence_refs"][0]
        assert evidence_ref.startswith("evidence-seg_")
        assert CONTEXT_RAG_CANDIDATES_KEY not in context

        analysis = runtime._analysis_subgraph.invoke(context)
        assert analysis["__target__"] == "planning_entry"
        assert analysis["work_analysis_result"]["work_facts"]

        planned = runtime._planning_subgraph.invoke(analysis)
        assert planned["__target__"] == "response_synthesis"
        assert planned["answer_draft"]["evidence_refs"] == [evidence_ref]
        planning_input = next(
            call["prompt_input"]
            for call in llm_runtime.calls
            if getattr(call["prompt_ref"], "prompt_id", None) == "planning.compose_answer"
        )
        assert isinstance(planning_input, dict)
        assert planning_input["work_analysis"] == analysis["work_analysis_result"]
    finally:
        runtime.close()


def test_edge_analysis_confirmation_never_enters_planning(tmp_path: Path) -> None:
    output = _analysis_output()
    output["status"] = "NEEDS_CONFIRMATION"
    output["confirmation"] = {
        "reason_code": "ANALYSIS_RELATIONSHIP_AMBIGUITY",
        "question": "Which task should be primary?",
    }
    database_path = _seed_runtime_database(tmp_path)
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _clear_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            output,
        ],
        gateway=FakeGoogleGateway(
            ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
        ),
        checkpoint_port=sqlite_checkpoint(database_path),
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
    )

    try:
        result = start_with_admission(runtime, database_path, _start_request())
        assert (
            result.payload["user_interrupt"]["origin_target"] == "analysis.assess_information_gaps"
        )
        snapshot = runtime._graph.get_state(
            runtime._config_for_thread("thread-1"),
            subgraphs=True,
        )
        assert snapshot.next == ("work_analysis",)
        assert snapshot.tasks[0].state.next == ("finalize",)
        assert snapshot.tasks[0].state.values["workflow_phase"] == "WAITING_CONFIRMATION"
        assert snapshot.values.get("plan_draft") is None
        assert snapshot.values.get("answer_draft") is None
    finally:
        runtime.close()
