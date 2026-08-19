"""C4: Work Analysis Confirmation -- nested subgraph checkpoint resume
integration tests.

Work Analysis's only NEEDS_CONFIRMATION trigger is ``work_analysis.analyze``
(``WorkAnalysisAgent.invoke_analyze_llm_from_retrieval_result``) returning
``status="NEEDS_CONFIRMATION"`` -- the single LLM step in this subgraph, run
only after Retrieval has already produced a SUFFICIENT/PARTIAL
``RetrievalResultV1`` and populated the run's ``RunScopedEvidenceStore``.

Unlike Request Understanding/Tool Route/Retrieval's own confirmation resume
(whose every dependency lives in checkpoint-persisted state), Work
Analysis's ``analyze`` also reads ``RunScopedEvidenceStore`` -- an
in-process, run-memory-only store owned by one ``LangGraphWorkflowRuntime``
instance (``runtime.py``'s ``self._evidence_store``, never SQLite-backed).
This is a pre-existing property of ``resolve_evidence_projection`` (present
before C4, on the OLD full-subgraph-restart resume path too), not something
the nested-checkpoint mechanism introduces -- so these tests resume against
the SAME runtime instance that ran Retrieval, matching the realistic
single-long-lived-process deployment these tests otherwise use ``.close()``
+ reconstruction to simulate for checkpoint-durable state.

These tests focus on: the interrupt genuinely living inside Work Analysis's
own nested task (not the shared Main-Graph ``waiting_confirmation`` node),
zero re-execution of Retrieval/Tool Route/provider reads on resume, exactly
one more real ``work_analysis.analyze`` call per round, retrieval-result
identity preservation, repeated confirmation rounds resolving inline, and
fail-closed invalid resume.
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
    _answer_output,
    _clear_intent,
    _llm_result,
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


def _analysis_output(
    status: str,
    *,
    confirmation: dict[str, object] | None = None,
    missing_information: list[str] | None = None,
    blockers: list[str] | None = None,
) -> dict[str, object]:
    """Status-parameterized ``work_analysis.analyze`` payload in
    ``test_runtime.py``'s own reference space (``evidence-seg-2`` /
    ``task:task-followup`` / ``seg-2``) -- the actual ids the full runtime's
    Retrieval fixture chain (``_clear_intent``/``_selection_output``/
    ``_sufficiency_output``) produces, distinct from
    ``tests.unit.application.workflows.test_work_analysis``'s own
    differently-scoped fixture reference space."""
    return {
        "schema_version": 1,
        "status": status,
        "summary": "The task context is enough to decide the next step.",
        "findings": (
            [
                {
                    "schema_version": 1,
                    "finding_id": "finding-1",
                    "kind": "RELATIONSHIP",
                    "statement": "The selected task provides enough context.",
                    "evidence_refs": ["evidence-seg-2"],
                    "resource_refs": ["task:task-followup"],
                    "segment_refs": ["seg-2"],
                    "related_resource_handles": ["task:task-followup"],
                    "reason_codes": ["EVIDENCE_SUPPORTED"],
                }
            ]
            if status != "BLOCKED"
            else []
        ),
        "missing_information": missing_information or [],
        "confirmation": confirmation,
        "blockers": blockers or (["Analysis cannot proceed."] if status == "BLOCKED" else []),
        "evidence_refs": ["evidence-seg-2"],
        "resource_refs": [
            {
                "resource_handle": "task:task-followup",
                "resource_type": "task",
                "resource_id": "task-followup",
            }
        ],
        "segment_refs": [
            {
                "segment_id": "seg-2",
                "resource_handle": "task:task-followup",
            }
        ],
    }


def _confirmation() -> dict[str, object]:
    return {
        "reason_code": "ANALYSIS_RELATIONSHIP_AMBIGUITY",
        "question": "Which task should be treated as the primary follow-up?",
    }


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


def _queue_more(llm_runtime: _QueuedLLMRuntime, payloads: list[object]) -> None:
    """Feed more responses into an already-constructed ``_QueuedLLMRuntime``
    ahead of a ``.resume()`` call. Deliberately reuses the SAME runtime/llm
    instance across start->resume in these tests (rather than the
    close()+reconstruct pattern C1/C2/C3's own confirmation tests use) --
    see the module docstring for why: ``RunScopedEvidenceStore`` is
    in-process/run-memory-only, unrelated to the nested-checkpoint mechanism
    under test here."""
    llm_runtime._queued.extend(_llm_result(item) for item in payloads)  # noqa: SLF001


def _nested_work_analysis_task(runtime: LangGraphWorkflowRuntime) -> Any:
    """The paused checkpoint's own task for the nested work_analysis
    subgraph -- asserting on this is what actually distinguishes "same
    nested checkpoint resume" from a full subgraph restart."""
    thread_config = runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
    snapshot = runtime._graph.get_state(thread_config, subgraphs=True)  # noqa: SLF001
    assert snapshot.next == ("work_analysis",)
    assert len(snapshot.tasks) == 1
    outer_task = snapshot.tasks[0]
    assert outer_task.name == "work_analysis"
    return outer_task


def _analyze_calls(llm_runtime: _QueuedLLMRuntime) -> list[dict[str, object]]:
    return [
        call
        for call in llm_runtime.calls
        if getattr(call["prompt_ref"], "prompt_id", None) == "work_analysis.analyze"
    ]


def _retrieval_calls(llm_runtime: _QueuedLLMRuntime) -> list[dict[str, object]]:
    return [
        call
        for call in llm_runtime.calls
        if str(getattr(call["prompt_ref"], "prompt_id", "")).startswith(
            ("retrieval.", "acquisition.")
        )
    ]


def _start_to_first_confirmation(
    *, database_path: Path, gateway: FakeGoogleGateway, checkpoint_path: Path, manifest_path: Path
) -> tuple[LangGraphWorkflowRuntime, _QueuedLLMRuntime, dict[str, Any]]:
    llm_runtime = _QueuedLLMRuntime(
        [
            _clear_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output("NEEDS_CONFIRMATION", confirmation=_confirmation()),
        ]
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="run",
    )
    first = runtime.start(_start_request())
    assert first.outcome is WorkflowOutcome.ACCEPTED
    return runtime, llm_runtime, first.payload


# --- T1 + T2: NEEDS_CONFIRMATION pauses inside Work Analysis's own nested
# task, same run/thread/owner. ---


def test_work_analysis_needs_confirmation_pauses_inside_own_nested_task(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-work-analysis-confirm.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
    )
    try:
        interrupt = payload["user_interrupt"]
        assert interrupt is not None
        assert interrupt["origin_target"] == "analysis.analyze"
        interrupt_id = interrupt["interrupt_id"]
        assert interrupt_id is not None

        # T1: nested pending task is genuinely "work_analysis", not the
        # shared Main-Graph "waiting_confirmation" node.
        outer_task = _nested_work_analysis_task(runtime)
        assert outer_task.state.next == ("finalize",)

        # T2: same run/thread, owner = WORK_ANALYSIS.
        connection = connect_sqlite(database_path)
        try:
            run_row = connection.execute(
                "SELECT status, langgraph_thread_id FROM runs WHERE id = 'run-1';"
            ).fetchone()
            assert run_row[0] == "WAITING_CONFIRMATION"
            assert run_row[1] == "thread-1"
        finally:
            connection.close()

        # Exactly one real analyze call happened before the pause.
        assert len(_analyze_calls(llm_runtime)) == 1
    finally:
        runtime.close()


# --- T3 + T4: resume re-executes neither Retrieval nor provider reads --
# only one more analyze call. ---


def test_work_analysis_resume_does_not_re_execute_retrieval(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-work-analysis-confirm-reuse.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
    )
    interrupt_id = payload["user_interrupt"]["interrupt_id"]
    reads_before_resume = len(gateway.call_log)
    assert reads_before_resume >= 1
    calls_before_resume = len(llm_runtime.calls)

    try:
        # 1 (classify) + 1 (tool_route auto-synth) + 1 (retrieval.plan_query
        # auto-synth) + 1 (select_evidence) + 1 (assess_sufficiency) +
        # 1 (analyze round1) = 6, + 1 (analyze round2 resolved) + 1 (answer)
        # = 8 = NORMAL_MAX_LLM_CALLS, so "review" (the 9th) is correctly
        # denied -- not queuing it and asserting budget-exhausted here
        # (rather than reaching COMPLETED) proves this is ordinary,
        # unchanged RunBudgetV1 accounting, matching C2-A/C2-B/C3's own
        # established arithmetic.
        _queue_more(llm_runtime, [_analysis_output("COMPLETE"), _answer_output()])
        with pytest.raises(LLMInvocationError) as excinfo:
            runtime.resume(
                WorkflowResumeRequest(
                    run_id="run-1",
                    workflow_key="thread-1",
                    resume_kind="CONFIRMATION",
                    resume_payload={
                        "schema_version": 1,
                        "interrupt_id": interrupt_id,
                        "response_kind": "FREE_TEXT",
                        "selected_option_ids": [],
                        "free_text": "The follow-up task is the primary one.",
                    },
                    correlation=WorkflowCorrelationContext(
                        request_id="request-2", command_id="command-2", api_contract_version="1"
                    ),
                )
            )
        assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED

        # T3: zero provider reads happened on resume -- Retrieval's
        # already-completed read from round 1 is never re-issued.
        assert len(gateway.call_log) == reads_before_resume

        # T4: no Retrieval/Tool Route LLM step re-ran either.
        calls_during_resume = llm_runtime.calls[calls_before_resume:]
        assert [
            call
            for call in calls_during_resume
            if str(getattr(call["prompt_ref"], "prompt_id", "")).startswith(
                ("retrieval.", "acquisition.", "tool_route.")
            )
        ] == []
        # Exactly one more analyze call resolved the confirmation.
        assert (
            len(
                [
                    call
                    for call in calls_during_resume
                    if getattr(call["prompt_ref"], "prompt_id", None) == "work_analysis.analyze"
                ]
            )
            == 1
        )
    finally:
        runtime.close()


# --- T5: retrieval_result identity preserved; invocation_id proves
# init/analyze never replayed from scratch. ---


def test_work_analysis_resume_preserves_retrieval_result_and_invocation_id(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-work-analysis-confirm-identity.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
    )
    interrupt_id = payload["user_interrupt"]["interrupt_id"]

    state_before = runtime._graph.get_state(  # noqa: SLF001
        runtime._invocation.config_for_thread("thread-1"), subgraphs=True  # noqa: SLF001
    )
    nested_before = state_before.tasks[0].state.values
    invocation_id_before = nested_before["__analysis_agent_local__"]["invocation_id"]
    retrieval_result_before = nested_before["retrieval_result"]

    try:
        _queue_more(llm_runtime, [_analysis_output("COMPLETE"), _answer_output()])
        with pytest.raises(LLMInvocationError) as excinfo:
            runtime.resume(
                WorkflowResumeRequest(
                    run_id="run-1",
                    workflow_key="thread-1",
                    resume_kind="CONFIRMATION",
                    resume_payload={
                        "schema_version": 1,
                        "interrupt_id": interrupt_id,
                        "response_kind": "FREE_TEXT",
                        "selected_option_ids": [],
                        "free_text": "The follow-up task is the primary one.",
                    },
                    correlation=WorkflowCorrelationContext(
                        request_id="request-2", command_id="command-2", api_contract_version="1"
                    ),
                )
            )
        assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED

        state = runtime._graph.get_state(  # noqa: SLF001
            runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
        ).values
        retrieval_result = state["retrieval_result"]
        assert retrieval_result == retrieval_result_before

        # T5: "init" (which mints a fresh invocation_id via
        # self._id_factory()) appears exactly once in the accumulated
        # agent_node_log for work_analysis -- if "init"/"analyze" had
        # genuinely replayed from START on resume, a second "init" entry
        # with a NEW invocation_id would show up here.
        node_log = state["trace_context"]["agent_node_log"]
        work_analysis_entries = [
            entry for entry in node_log if entry["agent_subgraph_id"] == "work_analysis"
        ]
        init_entries = [entry for entry in work_analysis_entries if entry["node_name"] == "init"]
        assert len(init_entries) == 1
        assert init_entries[0]["agent_invocation_id"] == invocation_id_before
        assert all(
            entry["agent_invocation_id"] == invocation_id_before
            for entry in work_analysis_entries
        )
    finally:
        runtime.close()


# --- T6: confirmation_response reaches work_analysis.analyze's prompt_input,
# and Prompt boundary excludes checkpoint/interrupt metadata. ---


def test_work_analysis_resume_applies_confirmation_response_within_prompt_boundary(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-work-analysis-confirm-prompt.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
    )
    interrupt_id = payload["user_interrupt"]["interrupt_id"]
    calls_before_resume = len(llm_runtime.calls)

    try:
        _queue_more(llm_runtime, [_analysis_output("COMPLETE"), _answer_output()])
        with pytest.raises(LLMInvocationError) as excinfo:
            runtime.resume(
                WorkflowResumeRequest(
                    run_id="run-1",
                    workflow_key="thread-1",
                    resume_kind="CONFIRMATION",
                    resume_payload={
                        "schema_version": 1,
                        "interrupt_id": interrupt_id,
                        "response_kind": "FREE_TEXT",
                        "selected_option_ids": [],
                        "free_text": "The follow-up task is the primary one.",
                    },
                    correlation=WorkflowCorrelationContext(
                        request_id="request-2", command_id="command-2", api_contract_version="1"
                    ),
                )
            )
        assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED

        calls_during_resume = llm_runtime.calls[calls_before_resume:]
        analyze_calls = [
            call
            for call in calls_during_resume
            if getattr(call["prompt_ref"], "prompt_id", None) == "work_analysis.analyze"
        ]
        assert len(analyze_calls) == 1
        prompt_input = analyze_calls[0]["prompt_input"]
        assert isinstance(prompt_input, dict)
        confirmation_response = prompt_input["confirmation_response"]
        assert isinstance(confirmation_response, dict)
        assert confirmation_response["free_text"] == "The follow-up task is the primary one."

        for forbidden_key in (
            "interrupt_id",
            "resume_target",
            "checkpoint",
            "owner_subgraph",
            "policy_confirmation_receipts",
        ):
            assert forbidden_key not in prompt_input
    finally:
        runtime.close()


# --- T7: repeated confirmation resolves inline, same nested checkpoint each
# round. ---


def test_work_analysis_resumes_second_consecutive_confirmation_round_via_same_nested_checkpoint(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-work-analysis-two-round.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
    )
    round1_interrupt_id = payload["user_interrupt"]["interrupt_id"]

    try:
        # --- Round 2: still ambiguous -- must pause again, still inside the
        # same nested subgraph. ---
        _queue_more(
            llm_runtime, [_analysis_output("NEEDS_CONFIRMATION", confirmation=_confirmation())]
        )
        second = runtime.resume(
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

        round2_task = _nested_work_analysis_task(runtime)
        assert round2_task.state.next == ("finalize",)
        round2_interrupt_id = second.payload["user_interrupt"]["interrupt_id"]
        assert second.payload["user_interrupt"]["origin_target"] == "analysis.analyze"
        assert round2_interrupt_id != round1_interrupt_id

        # --- Round 3: resolved -- Work Analysis completes, run proceeds
        # downstream. 7 real calls already spent (classify + tool_route +
        # plan_query + select_evidence + assess_sufficiency + round1
        # analyze + round2 analyze) + round3 analyze = 8 =
        # NORMAL_MAX_LLM_CALLS, so "answer_only" (the 9th) is correctly
        # denied. ---
        calls_before_round3 = len(llm_runtime.calls)
        _queue_more(llm_runtime, [_analysis_output("COMPLETE")])
        with pytest.raises(LLMInvocationError) as excinfo:
            runtime.resume(
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
        calls_during_round3 = llm_runtime.calls[calls_before_round3:]
        assert (
            len(
                [
                    call
                    for call in calls_during_round3
                    if getattr(call["prompt_ref"], "prompt_id", None) == "work_analysis.analyze"
                ]
            )
            == 1
        )
        # No Retrieval/provider re-execution at any point across rounds 2-3.
        assert [
            call
            for call in llm_runtime.calls
            if str(getattr(call["prompt_ref"], "prompt_id", "")).startswith(
                ("retrieval.", "acquisition.", "tool_route.")
            )
        ] == _retrieval_and_tool_route_calls_from_round1(llm_runtime)

        state = runtime._graph.get_state(  # noqa: SLF001
            runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
        ).values
        assert state["analysis_result"] is not None
        assert state["analysis_result"]["status"] == "COMPLETE"
    finally:
        runtime.close()


def _retrieval_and_tool_route_calls_from_round1(
    llm_runtime: _QueuedLLMRuntime,
) -> list[dict[str, object]]:
    """The Retrieval/Tool Route calls that happened during round 1's initial
    ``.start()`` only -- used to prove no further such call was added in
    rounds 2-3."""
    return [
        call
        for call in llm_runtime.calls
        if str(getattr(call["prompt_ref"], "prompt_id", "")).startswith(
            ("retrieval.", "acquisition.", "tool_route.")
        )
    ]


# --- T11: invalid resume fails closed. ---


def test_work_analysis_resume_rejects_wrong_interrupt_id(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-work-analysis-invalid.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, _payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
    )
    calls_before_resume = len(llm_runtime.calls)
    try:
        with pytest.raises(ValueError, match="interrupt_id"):
            runtime.resume(
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
        # Fails closed: no further Provider/LLM call happened while
        # validating the resume payload.
        assert len(llm_runtime.calls) == calls_before_resume
    finally:
        runtime.close()


def test_work_analysis_resume_rejects_option_id_outside_allowed_scope(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-work-analysis-invalid-option.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
    )
    interrupt_id = payload["user_interrupt"]["interrupt_id"]
    # NEEDS_CONFIRMATION's question here is always free-text (options=[]) --
    # a closed-choice OPTION_SELECTION response must be rejected as outside
    # scope.
    assert payload["user_interrupt"]["options"] == []

    try:
        with pytest.raises(ValueError, match="option"):
            runtime.resume(
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
        runtime.close()


# --- T9: existing NEEDS_MORE_DATA disposition (Work Analysis -> Retrieval)
# is a pure routing decision made by unchanged code (_finalize_resolved ->
# route_supervisor -> _route_analysis's NEEDS_MORE_DATA branch, which this
# subgraph's new confirmation-interception guard cannot reach: the guard is
# gated on ``result["status"] == "NEEDS_CONFIRMATION"`` and always false
# here). Already covered end-to-end by
# tests/unit/application/workflows/test_supervisor.py and
# tests/unit/application/workflows/test_work_analysis.py's own
# NEEDS_MORE_DATA cases (unchanged by C4) -- driving a full second Retrieval
# round through this integration runtime would only re-test Retrieval V2's
# own follow-up-round machinery, out of C4's scope.


# --- T8: existing COMPLETE happy path (no confirmation) unaffected. ---


def test_work_analysis_happy_path_without_confirmation_completes(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _clear_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output("COMPLETE"),
            _answer_output(),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-work-analysis-happy.db",
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
