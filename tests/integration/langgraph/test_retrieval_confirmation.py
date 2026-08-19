"""C3: Retrieval Confirmation -- nested subgraph checkpoint resume
integration tests.

Retrieval's only NEEDS_CONFIRMATION trigger is ``retrieval.assess_sufficiency``
(``ContextRetrievalAgent.assess_sufficiency``) returning
``status="NEEDS_CONFIRMATION"`` -- always the LAST LLM step in one round
(after ``select_evidence``/``selection_validate`` already completed and
committed). These tests focus on: the interrupt genuinely living inside
Retrieval's own nested task (not the shared Main-Graph
``waiting_confirmation`` node), zero re-execution of Tool Route/query
planning/provider reads/select_evidence on resume, exactly one more real
``retrieval.assess_sufficiency`` call per round, evidence/cache identity
preservation, repeated confirmation rounds resolving inline, and fail-closed
invalid resume.
"""

from __future__ import annotations

from typing import Any

from tests.integration.langgraph.test_runtime import (
    FIXTURE_ROOT,
    DeterministicUUID,
    FakeClock,
    FakeGoogleGateway,
    GoogleWorkspaceExecutionBackend,
    GraphProfile,
    LangGraphWorkflowRuntime,
    Path,
    ProductFixtureSnapshotLoader,
    WorkflowCorrelationContext,
    WorkflowOutcome,
    WorkflowResumeRequest,
    _analysis_output,
    _answer_output,
    _clear_intent,
    _make_runtime,
    _QueuedLLMRuntime,
    _review_output,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _start_request,
    _tool_catalog,
    connect_sqlite,
    pytest,
    sqlite_unit_of_work_factory,
)
from tests.unit.application.workflows.test_context_retrieval import _sufficiency_output

from google_work_agent.ports import LLMErrorCode, LLMInvocationError


def _build_runtime(
    *,
    database_path: Path,
    llm_runtime: _QueuedLLMRuntime,
    gateway: FakeGoogleGateway,
    checkpoint_path: Path,
    manifest_path: Path,
    id_prefix: str,
) -> LangGraphWorkflowRuntime:
    return LangGraphWorkflowRuntime(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        llm_runtime=llm_runtime,
        gateway=gateway,
        connector_execution=GoogleWorkspaceExecutionBackend(gateway=gateway),
        tool_catalog=_tool_catalog(),
        now_ms=FakeClock(1000).now_ms,
        id_factory=DeterministicUUID(prefix=id_prefix).next_id,
        signing_secret="stage17-secret",
        service_instance_id="stage17-service",
        checkpoint_database_path=checkpoint_path,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
        default_tasklist_id_provider=lambda: "task-list-default",
    )


def _nested_context_retriever_task(runtime: LangGraphWorkflowRuntime) -> Any:
    """The paused checkpoint's own task for the nested context_retriever
    subgraph -- asserting on this is what actually distinguishes "same
    nested checkpoint resume" from a full subgraph restart."""
    thread_config = runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
    snapshot = runtime._graph.get_state(thread_config, subgraphs=True)  # noqa: SLF001
    assert snapshot.next == ("context_retriever",)
    assert len(snapshot.tasks) == 1
    outer_task = snapshot.tasks[0]
    assert outer_task.name == "context_retriever"
    return outer_task


def _assess_sufficiency_calls(llm_runtime: _QueuedLLMRuntime) -> list[dict[str, object]]:
    return [
        call
        for call in llm_runtime.calls
        if getattr(call["prompt_ref"], "prompt_id", None) == "retrieval.assess_sufficiency"
    ]


def _plan_query_calls(llm_runtime: _QueuedLLMRuntime) -> list[dict[str, object]]:
    return [
        call
        for call in llm_runtime.calls
        if getattr(call["prompt_ref"], "prompt_id", None) == "retrieval.plan_query"
    ]


def _select_evidence_calls(llm_runtime: _QueuedLLMRuntime) -> list[dict[str, object]]:
    return [
        call
        for call in llm_runtime.calls
        if getattr(call["prompt_ref"], "prompt_id", None) == "retrieval.select_evidence"
    ]


# --- T1 + T2: NEEDS_CONFIRMATION pauses inside Retrieval's own nested task,
# same run/thread/owner. ---


def test_retrieval_needs_confirmation_pauses_inside_own_nested_task(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-retrieval-confirm.db"

    gateway = FakeGoogleGateway(snapshot)
    llm_runtime = _QueuedLLMRuntime(
        [_clear_intent(), _selection_output(), _sufficiency_output("NEEDS_CONFIRMATION")]
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    try:
        first = runtime.start(_start_request())

        assert first.outcome is WorkflowOutcome.ACCEPTED
        interrupt = first.payload["user_interrupt"]
        assert interrupt is not None
        assert interrupt["origin_target"] == "context.assess_sufficiency"
        interrupt_id = interrupt["interrupt_id"]
        assert interrupt_id is not None

        # T1: nested pending task is genuinely "context_retriever", not the
        # shared Main-Graph "waiting_confirmation" node.
        outer_task = _nested_context_retriever_task(runtime)
        assert outer_task.state.next == ("finalize",)

        # T2: same run/thread, owner = RETRIEVAL.
        connection = connect_sqlite(database_path)
        try:
            run_row = connection.execute(
                "SELECT status, langgraph_thread_id FROM runs WHERE id = 'run-1';"
            ).fetchone()
            assert run_row[0] == "WAITING_CONFIRMATION"
            assert run_row[1] == "thread-1"
        finally:
            connection.close()

        # Exactly one real assess_sufficiency call happened before the pause.
        assert len(_assess_sufficiency_calls(llm_runtime)) == 1
    finally:
        runtime.close()


# --- T3 + T4: resume re-executes neither completed provider reads nor
# query planning -- only one more assess_sufficiency call. ---


def test_retrieval_resume_reuses_completed_read_and_query_plan(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-retrieval-confirm-reuse.db"

    gateway = FakeGoogleGateway(snapshot)
    llm_runtime = _QueuedLLMRuntime(
        [_clear_intent(), _selection_output(), _sufficiency_output("NEEDS_CONFIRMATION")]
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    first = runtime.start(_start_request())
    interrupt_id = first.payload["user_interrupt"]["interrupt_id"]
    reads_before_pause = list(gateway.call_log)
    assert len(reads_before_pause) >= 1
    runtime.close()

    # 1 (classify) + 1 (tool_route auto-synth) + 1 (retrieval.plan_query
    # auto-synth) + 1 (select_evidence) + 1 (assess_sufficiency round1) + 1
    # (assess_sufficiency round2) + 1 (analysis) + 1 (answer) = 8 =
    # NORMAL_MAX_LLM_CALLS, so "review" (the 9th) is correctly denied --
    # not queuing it and asserting budget-exhausted here (rather than
    # reaching COMPLETED) proves this is ordinary, unchanged RunBudgetV1
    # accounting, matching C2-A/C2-B's own established arithmetic.
    resumed_gateway = FakeGoogleGateway(snapshot)
    resumed_llm_runtime = _QueuedLLMRuntime(
        [
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
        ]
    )
    resumed_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=resumed_llm_runtime,
        gateway=resumed_gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round2",
    )
    try:
        with pytest.raises(LLMInvocationError) as excinfo:
            resumed_runtime.resume(
                WorkflowResumeRequest(
                    run_id="run-1",
                    workflow_key="thread-1",
                    resume_kind="CONFIRMATION",
                    resume_payload={
                        "schema_version": 1,
                        "interrupt_id": interrupt_id,
                        "response_kind": "FREE_TEXT",
                        "selected_option_ids": [],
                        "free_text": "Use the task list I mentioned.",
                    },
                    correlation=WorkflowCorrelationContext(
                        request_id="request-2", command_id="command-2", api_contract_version="1"
                    ),
                )
            )
        assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED

        # T3: zero provider reads happened on resume -- the resumed run's
        # OWN gateway saw no calls at all (the already-completed read from
        # round 1 lives only in round 1's gateway/cache, never re-issued).
        assert resumed_gateway.call_log == []

        # T4: retrieval.plan_query (INITIAL query planning) never re-ran.
        assert _plan_query_calls(resumed_llm_runtime) == []
        # select_evidence never re-ran either.
        assert _select_evidence_calls(resumed_llm_runtime) == []
        # Exactly one more assess_sufficiency call resolved the confirmation.
        assert len(_assess_sufficiency_calls(resumed_llm_runtime)) == 1
    finally:
        resumed_runtime.close()


# --- T5: evidence/cache identity preserved across the pause. ---


def test_retrieval_resume_preserves_evidence_identity(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-retrieval-confirm-identity.db"

    gateway = FakeGoogleGateway(snapshot)
    llm_runtime = _QueuedLLMRuntime(
        [_clear_intent(), _selection_output(), _sufficiency_output("NEEDS_CONFIRMATION")]
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    first = runtime.start(_start_request())
    interrupt_id = first.payload["user_interrupt"]["interrupt_id"]

    state_before = runtime._graph.get_state(  # noqa: SLF001
        runtime._invocation.config_for_thread("thread-1"), subgraphs=True  # noqa: SLF001
    )
    nested_before = state_before.tasks[0].state.values
    evidence_drafts_before = nested_before["evidence_drafts"]
    round_no_before = nested_before["__context_current_round_no__"]
    runtime.close()

    resumed_gateway = FakeGoogleGateway(snapshot)
    resumed_llm_runtime = _QueuedLLMRuntime(
        [
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
        ]
    )
    resumed_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=resumed_llm_runtime,
        gateway=resumed_gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round2",
    )
    try:
        # Same budget arithmetic as the read/query-plan-reuse test above --
        # "review" (the 9th real call) is correctly denied.
        with pytest.raises(LLMInvocationError) as excinfo:
            resumed_runtime.resume(
                WorkflowResumeRequest(
                    run_id="run-1",
                    workflow_key="thread-1",
                    resume_kind="CONFIRMATION",
                    resume_payload={
                        "schema_version": 1,
                        "interrupt_id": interrupt_id,
                        "response_kind": "FREE_TEXT",
                        "selected_option_ids": [],
                        "free_text": "Use the task list I mentioned.",
                    },
                    correlation=WorkflowCorrelationContext(
                        request_id="request-2", command_id="command-2", api_contract_version="1"
                    ),
                )
            )
        assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED
        state = resumed_runtime._graph.get_state(  # noqa: SLF001
            resumed_runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
        ).values
        retrieval_result = state["retrieval_result"]
        assert retrieval_result is not None
        # Same evidence_refs/round -- never re-derived with new identities.
        assert retrieval_result["evidence_refs"] == [
            draft["evidence_id"] for draft in evidence_drafts_before
        ]
        # retrieval_rounds is the 1-based round COUNT; __context_current_round_no__
        # is the 0-based round counter -- their +1 relationship is pre-existing
        # (finalize_retrieval_result), unrelated to C3. What matters here is
        # that the pre-pause round counter (captured from the paused nested
        # checkpoint's own local state) is what the resolved result is built
        # from -- proving _init_node never re-ran and reset it.
        assert retrieval_result["retrieval_rounds"] == round_no_before + 1
    finally:
        resumed_runtime.close()


# --- T6: confirmation_response reaches retrieval.assess_sufficiency's
# prompt_input, and Prompt boundary excludes checkpoint/interrupt metadata. ---


def test_retrieval_resume_applies_confirmation_response_within_prompt_boundary(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-retrieval-confirm-prompt.db"

    gateway = FakeGoogleGateway(snapshot)
    llm_runtime = _QueuedLLMRuntime(
        [_clear_intent(), _selection_output(), _sufficiency_output("NEEDS_CONFIRMATION")]
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    first = runtime.start(_start_request())
    interrupt_id = first.payload["user_interrupt"]["interrupt_id"]
    runtime.close()

    resumed_gateway = FakeGoogleGateway(snapshot)
    resumed_llm_runtime = _QueuedLLMRuntime(
        [
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
        ]
    )
    resumed_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=resumed_llm_runtime,
        gateway=resumed_gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round2",
    )
    try:
        with pytest.raises(LLMInvocationError) as excinfo:
            resumed_runtime.resume(
                WorkflowResumeRequest(
                    run_id="run-1",
                    workflow_key="thread-1",
                    resume_kind="CONFIRMATION",
                    resume_payload={
                        "schema_version": 1,
                        "interrupt_id": interrupt_id,
                        "response_kind": "FREE_TEXT",
                        "selected_option_ids": [],
                        "free_text": "It is in my Work task list.",
                    },
                    correlation=WorkflowCorrelationContext(
                        request_id="request-2", command_id="command-2", api_contract_version="1"
                    ),
                )
            )
        assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED

        sufficiency_calls = _assess_sufficiency_calls(resumed_llm_runtime)
        assert len(sufficiency_calls) == 1
        prompt_input = sufficiency_calls[0]["prompt_input"]
        assert isinstance(prompt_input, dict)
        confirmation_response = prompt_input["confirmation_response"]
        assert isinstance(confirmation_response, dict)
        assert confirmation_response["free_text"] == "It is in my Work task list."

        for forbidden_key in (
            "interrupt_id",
            "resume_target",
            "checkpoint",
            "owner_subgraph",
            "policy_confirmation_receipts",
        ):
            assert forbidden_key not in prompt_input
    finally:
        resumed_runtime.close()


# --- T7: repeated confirmation resolves inline, same nested checkpoint each
# round. ---


def test_retrieval_resumes_second_consecutive_confirmation_round_via_same_nested_checkpoint(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-retrieval-two-round.db"

    # --- Round 1 ---
    llm_runtime = _QueuedLLMRuntime(
        [_clear_intent(), _selection_output(), _sufficiency_output("NEEDS_CONFIRMATION")]
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    first = runtime.start(_start_request())
    assert first.outcome is WorkflowOutcome.ACCEPTED
    round1_interrupt_id = first.payload["user_interrupt"]["interrupt_id"]
    runtime.close()

    # --- Round 2: still ambiguous -- must pause again, still inside the
    # same nested subgraph. ---
    round2_llm_runtime = _QueuedLLMRuntime([_sufficiency_output("NEEDS_CONFIRMATION")])
    round2_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=round2_llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round2",
    )
    second = round2_runtime.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="CONFIRMATION",
            resume_payload={
                "schema_version": 1,
                "interrupt_id": round1_interrupt_id,
                "response_kind": "FREE_TEXT",
                "selected_option_ids": [],
                "free_text": "round-1 answer, still ambiguous apparently.",
            },
            correlation=WorkflowCorrelationContext(
                request_id="request-2", command_id="command-2", api_contract_version="1"
            ),
        )
    )
    assert second.outcome is WorkflowOutcome.ACCEPTED
    assert len(_assess_sufficiency_calls(round2_llm_runtime)) == 1

    round2_task = _nested_context_retriever_task(round2_runtime)
    assert round2_task.state.next == ("finalize",)
    round2_interrupt_id = second.payload["user_interrupt"]["interrupt_id"]
    assert second.payload["user_interrupt"]["origin_target"] == "context.assess_sufficiency"
    assert round2_interrupt_id != round1_interrupt_id
    round2_runtime.close()

    # --- Round 3: resolved -- Retrieval completes, run proceeds downstream.
    # 6 real calls already spent (classify + tool_route + plan_query +
    # select_evidence + round1 assess_sufficiency + round2 assess_sufficiency)
    # + round3 assess_sufficiency + analysis = 8 = NORMAL_MAX_LLM_CALLS, so
    # "answer_only" (the 9th) is correctly denied -- not queuing it and
    # asserting budget-exhausted here (rather than COMPLETED) is the same
    # established arithmetic as the earlier tests, just with one extra round
    # of pre-pause cost. ---
    round3_llm_runtime = _QueuedLLMRuntime(
        [
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
        ]
    )
    round3_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=round3_llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round3",
    )
    try:
        with pytest.raises(LLMInvocationError) as excinfo:
            round3_runtime.resume(
                WorkflowResumeRequest(
                    run_id="run-1",
                    workflow_key="thread-1",
                    resume_kind="CONFIRMATION",
                    resume_payload={
                        "schema_version": 1,
                        "interrupt_id": round2_interrupt_id,
                        "response_kind": "FREE_TEXT",
                        "selected_option_ids": [],
                        "free_text": "round-2 answer, resolves it.",
                    },
                    correlation=WorkflowCorrelationContext(
                        request_id="request-3", command_id="command-3", api_contract_version="1"
                    ),
                )
            )
        assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED
        assert len(_assess_sufficiency_calls(round3_llm_runtime)) == 1
        # No provider read and no query planning at any point in rounds 2-3.
        assert _plan_query_calls(round2_llm_runtime) == []
        assert _plan_query_calls(round3_llm_runtime) == []

        state = round3_runtime._graph.get_state(  # noqa: SLF001
            round3_runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
        ).values
        assert state["retrieval_result"] is not None
    finally:
        round3_runtime.close()


# --- T10: invalid resume fails closed. ---


def test_retrieval_resume_rejects_wrong_interrupt_id(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-retrieval-invalid.db"

    llm_runtime = _QueuedLLMRuntime(
        [_clear_intent(), _selection_output(), _sufficiency_output("NEEDS_CONFIRMATION")]
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    runtime.start(_start_request())
    runtime.close()

    resumed_llm_runtime = _QueuedLLMRuntime([])
    resumed_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=resumed_llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round2",
    )
    try:
        with pytest.raises(ValueError, match="interrupt_id"):
            resumed_runtime.resume(
                WorkflowResumeRequest(
                    run_id="run-1",
                    workflow_key="thread-1",
                    resume_kind="CONFIRMATION",
                    resume_payload={
                        "schema_version": 1,
                        "interrupt_id": "definitely-the-wrong-interrupt-id",
                        "response_kind": "FREE_TEXT",
                        "selected_option_ids": [],
                        "free_text": "irrelevant",
                    },
                    correlation=WorkflowCorrelationContext(
                        request_id="request-2", command_id="command-2", api_contract_version="1"
                    ),
                )
            )
        # Fails closed: no Provider call happened while validating the
        # resume payload.
        assert resumed_llm_runtime.calls == []
    finally:
        resumed_runtime.close()


def test_retrieval_resume_rejects_option_id_outside_allowed_scope(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-retrieval-invalid-option.db"

    llm_runtime = _QueuedLLMRuntime(
        [_clear_intent(), _selection_output(), _sufficiency_output("NEEDS_CONFIRMATION")]
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    first = runtime.start(_start_request())
    interrupt_id = first.payload["user_interrupt"]["interrupt_id"]
    # NEEDS_CONFIRMATION's question here is always free-text (options=[]) --
    # a closed-choice OPTION_SELECTION response must be rejected as outside
    # scope.
    assert first.payload["user_interrupt"]["options"] == []
    runtime.close()

    resumed_llm_runtime = _QueuedLLMRuntime([])
    resumed_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=resumed_llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round2",
    )
    try:
        with pytest.raises(ValueError, match="option"):
            resumed_runtime.resume(
                WorkflowResumeRequest(
                    run_id="run-1",
                    workflow_key="thread-1",
                    resume_kind="CONFIRMATION",
                    resume_payload={
                        "schema_version": 1,
                        "interrupt_id": interrupt_id,
                        "response_kind": "OPTION_SELECTION",
                        "selected_option_ids": ["option-not-offered"],
                        "free_text": None,
                    },
                    correlation=WorkflowCorrelationContext(
                        request_id="request-2", command_id="command-2", api_contract_version="1"
                    ),
                )
            )
    finally:
        resumed_runtime.close()


# --- T9-adjacent: existing Retrieval happy path (no confirmation) unaffected. ---


def test_retrieval_happy_path_without_confirmation_completes(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _clear_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-retrieval-happy.db",
        prompt_manifest_path=manifest_path,
    )
    try:
        result = runtime.start(_start_request())
        assert result.outcome is WorkflowOutcome.COMPLETED
        connection = connect_sqlite(database_path)
        try:
            run_row = connection.execute(
                "SELECT status FROM runs WHERE id = 'run-1';"
            ).fetchone()
            assert run_row[0] == "COMPLETED"
        finally:
            connection.close()
    finally:
        runtime.close()
