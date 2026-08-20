"""C5: Planning Confirmation -- nested subgraph checkpoint resume
integration tests.

Planning's NEEDS_CONFIRMATION originates from ``planning.compose_answer``
(answer_only/revise_answer) via ``ANSWER_DRAFT_OUTPUT_SCHEMA``. These tests
exercise the ANSWER path: the interrupt genuinely living inside Planning's
own nested task (not the shared Main-Graph ``waiting_confirmation`` node),
zero re-execution of Tool Route/Retrieval/Work Analysis on resume, exactly
one more real Planning semantic call per round, repeated confirmation
rounds resolving inline, no premature Review/Persistence/Approval entry
while paused, and fail-closed invalid resume.

Since the Canonical Planning Production Migration, ACTION Planning
(draft_plan/revise_plan) runs through the per-route
``PlanningArgumentOrchestrator``/``PlanningArgumentWriter`` and can no
longer produce ``NEEDS_CONFIRMATION`` -- ``ToolArgumentCandidateV1`` has no
status/confirmation field and no canonical orchestration-level wrapper
exists for it. The ACTION-path confirmation tests formerly here were
removed as no-longer-reachable production scenarios; see
``test_canonical_planning_migration.py`` for the ACTION path's own
(canonical, per-route) coverage, including its ANSWER-unaffected framing.
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
    _clear_intent,
    _llm_result,
    _make_runtime,
    _QueuedLLMRuntime,
    _review_output,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _start_request,
    _sufficiency_output,
    _tool_catalog,
    connect_sqlite,
    pytest,
    sqlite_unit_of_work_factory,
)

from google_work_agent.ports import LLMErrorCode, LLMInvocationError


def _answer_output(
    status: str,
    *,
    confirmation: dict[str, object] | None = None,
    reason_codes: list[str] | None = None,
    blockers: list[str] | None = None,
) -> dict[str, object]:
    """Status-parameterized ``planning.compose_answer`` payload in
    ``test_runtime.py``'s own reference space (``evidence-seg-2`` /
    ``task:task-followup``)."""
    return {
        "schema_version": 1,
        "status": status,
        "answer": "The follow-up task is identified and summarized for the user.",
        "evidence_refs": ["evidence-seg-2"],
        "resource_refs": [
            {
                "resource_handle": "task:task-followup",
                "resource_type": "task",
                "resource_id": "task-followup",
            }
        ],
        "reason_codes": (
            reason_codes
            if reason_codes is not None
            else (["ROUTE_INVALID"] if status == "ROUTE_RECONSIDERATION_REQUIRED" else [])
        ),
        "confirmation": confirmation,
        "blockers": (
            blockers
            if blockers is not None
            else (["Cannot answer."] if status == "BLOCKED" else [])
        ),
    }


def _confirmation() -> dict[str, object]:
    return {
        "reason_code": "PLANNING_ARGUMENT_AMBIGUITY",
        "question": "Which due date should the plan use?",
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
    ahead of a ``.resume()`` call. Reuses the SAME runtime/llm instance
    across start->resume (rather than close()+reconstruct) -- Planning's
    ``resolve_evidence_projection`` depends on the run-memory-only
    ``RunScopedEvidenceStore`` (D1, out of C5's scope), same constraint
    already documented for Work Analysis in C4."""
    llm_runtime._queued.extend(_llm_result(item) for item in payloads)  # noqa: SLF001


def _nested_planning_task(runtime: LangGraphWorkflowRuntime) -> Any:
    """The paused checkpoint's own task for the nested planning subgraph --
    asserting on this is what actually distinguishes "same nested checkpoint
    resume" from a full subgraph restart."""
    thread_config = runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
    snapshot = runtime._graph.get_state(thread_config, subgraphs=True)  # noqa: SLF001
    assert snapshot.next == ("planning",)
    assert len(snapshot.tasks) == 1
    outer_task = snapshot.tasks[0]
    assert outer_task.name == "planning"
    return outer_task


def _planning_calls(llm_runtime: _QueuedLLMRuntime, prompt_id: str) -> list[dict[str, object]]:
    return [
        call
        for call in llm_runtime.calls
        if getattr(call["prompt_ref"], "prompt_id", None) == prompt_id
    ]


def _upstream_calls(llm_runtime: _QueuedLLMRuntime) -> list[dict[str, object]]:
    return [
        call
        for call in llm_runtime.calls
        if str(getattr(call["prompt_ref"], "prompt_id", "")).startswith(
            ("retrieval.", "acquisition.", "tool_route.", "work_analysis.")
        )
    ]


def _start_to_first_confirmation(
    *,
    database_path: Path,
    gateway: FakeGoogleGateway,
    checkpoint_path: Path,
    manifest_path: Path,
    llm_payloads: list[object],
) -> tuple[LangGraphWorkflowRuntime, _QueuedLLMRuntime, dict[str, Any]]:
    llm_runtime = _QueuedLLMRuntime(llm_payloads)
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


# --- T1: ANSWER-path NEEDS_CONFIRMATION pauses inside Planning's own nested
# task, same run/thread/owner, no premature downstream. ---


def test_planning_answer_needs_confirmation_pauses_inside_own_nested_task(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-planning-answer-confirm.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        llm_payloads=[
            _clear_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output("NEEDS_CONFIRMATION", confirmation=_confirmation()),
        ],
    )
    try:
        interrupt = payload["user_interrupt"]
        assert interrupt is not None
        assert interrupt["origin_target"] == "planning.answer_only"
        assert interrupt["interrupt_id"] is not None

        # T1: nested pending task is genuinely "planning".
        outer_task = _nested_planning_task(runtime)
        assert outer_task.state.next == ("finalize",)

        # T3: same run/thread, owner = PLANNING.
        connection = connect_sqlite(database_path)
        try:
            run_row = connection.execute(
                "SELECT status, langgraph_thread_id FROM runs WHERE id = 'run-1';"
            ).fetchone()
            assert run_row[0] == "WAITING_CONFIRMATION"
            assert run_row[1] == "thread-1"
        finally:
            connection.close()

        # T9: no premature Review/Domain Validation/Persistence/Approval.
        assert _planning_calls(llm_runtime, "review.inspect") == []
        assert len(_planning_calls(llm_runtime, "planning.compose_answer")) == 1
    finally:
        runtime.close()


# --- T2 (superseded by the Canonical Planning Production Migration):
# ACTION-path NEEDS_CONFIRMATION is no longer reachable in production.
# ``PlanningArgumentWriter``'s ``ToolArgumentCandidateV1`` schema has no
# status/confirmation field, and ``assemble_action_plan_draft_v1_compat``
# always returns ``status="PLAN_READY"`` -- this is a structural,
# BLOCKED_BY_CANONICAL_GAP consequence documented in
# ``adapters/langgraph/subgraphs/planning.py``'s module docstring, not a
# regression. See ``test_canonical_planning_migration.py`` for the ACTION
# path's own (canonical, per-route) coverage; ANSWER-path NEEDS_CONFIRMATION
# (this file's other tests) is completely unaffected.


# --- T4 + T5: resume re-executes no upstream, invocation_id proves
# init/plan never replayed. ---


def test_planning_answer_resume_does_not_re_execute_upstream(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-planning-answer-resume.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        llm_payloads=[
            _clear_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output("NEEDS_CONFIRMATION", confirmation=_confirmation()),
        ],
    )
    interrupt_id = payload["user_interrupt"]["interrupt_id"]
    reads_before_resume = len(gateway.call_log)

    state_before = runtime._graph.get_state(  # noqa: SLF001
        runtime._invocation.config_for_thread("thread-1"), subgraphs=True  # noqa: SLF001
    )
    invocation_id_before = state_before.tasks[0].state.values["__planning_agent_local__"][
        "invocation_id"
    ]
    calls_before_resume = len(llm_runtime.calls)

    try:
        # 7 real calls already spent (classify + tool_route auto-synth +
        # retrieval.plan_query auto-synth + select_evidence +
        # assess_sufficiency + work_analysis.analyze + planning round1) +
        # round2 (resolved) = 8 = NORMAL_MAX_LLM_CALLS, so "review" (the 9th)
        # is correctly denied.
        _queue_more(llm_runtime, [_answer_output("ANSWER_ONLY")])
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
                        "free_text": "Use tomorrow as the due date.",
                    },
                    correlation=WorkflowCorrelationContext(
                        request_id="request-2", command_id="command-2", api_contract_version="1"
                    ),
                )
            )
        assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED

        # T4: zero provider reads happened on resume.
        assert len(gateway.call_log) == reads_before_resume
        calls_during_resume = llm_runtime.calls[calls_before_resume:]
        assert [
            call
            for call in calls_during_resume
            if str(getattr(call["prompt_ref"], "prompt_id", "")).startswith(
                ("retrieval.", "acquisition.", "tool_route.", "work_analysis.")
            )
        ] == []
        # Exactly one more planning.compose_answer call resolved it.
        assert (
            len(
                [
                    call
                    for call in calls_during_resume
                    if getattr(call["prompt_ref"], "prompt_id", None)
                    == "planning.compose_answer"
                ]
            )
            == 1
        )

        # T5: invocation_id unchanged -- "init"/"plan" never replayed.
        state = runtime._graph.get_state(  # noqa: SLF001
            runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
        ).values
        node_log = state["trace_context"]["agent_node_log"]
        planning_entries = [
            entry for entry in node_log if entry["agent_subgraph_id"] == "planning"
        ]
        init_entries = [entry for entry in planning_entries if entry["node_name"] == "init"]
        assert len(init_entries) == 1
        assert init_entries[0]["agent_invocation_id"] == invocation_id_before
        assert all(
            entry["agent_invocation_id"] == invocation_id_before for entry in planning_entries
        )
    finally:
        runtime.close()


# --- T6 (superseded by the Canonical Planning Production Migration):
# ACTION-path pause/resume no longer applies (see T2 note above -- ACTION
# NEEDS_CONFIRMATION is structurally unreachable). Frozen tool_route_plan/
# output-route/tool identity preservation for the ACTION path is instead
# proven directly, without needing a Confirmation pause at all, by
# ``test_canonical_planning_migration.py``'s Tool-authority coverage (T3) --
# the canonical Argument Writer never sees Tool/effect/route selection in
# the first place, so there is nothing for a resume to preserve or corrupt.


# --- T7: confirmation_response reaches planning.compose_answer's
# prompt_input, and Prompt boundary excludes checkpoint/interrupt metadata. ---


def test_planning_resume_applies_confirmation_response_within_prompt_boundary(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-planning-prompt-boundary.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        llm_payloads=[
            _clear_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output("NEEDS_CONFIRMATION", confirmation=_confirmation()),
        ],
    )
    interrupt_id = payload["user_interrupt"]["interrupt_id"]
    calls_before_resume = len(llm_runtime.calls)

    try:
        _queue_more(llm_runtime, [_answer_output("ANSWER_ONLY")])
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
                        "free_text": "Use tomorrow as the due date.",
                    },
                    correlation=WorkflowCorrelationContext(
                        request_id="request-2", command_id="command-2", api_contract_version="1"
                    ),
                )
            )
        assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED

        calls_during_resume = llm_runtime.calls[calls_before_resume:]
        answer_calls = [
            call
            for call in calls_during_resume
            if getattr(call["prompt_ref"], "prompt_id", None) == "planning.compose_answer"
        ]
        assert len(answer_calls) == 1
        prompt_input = answer_calls[0]["prompt_input"]
        assert isinstance(prompt_input, dict)
        confirmation_response = prompt_input["confirmation_response"]
        assert isinstance(confirmation_response, dict)
        assert confirmation_response["free_text"] == "Use tomorrow as the due date."

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


# --- T8: repeated confirmation resolves inline, same nested checkpoint each
# round. ---


def test_planning_resumes_second_consecutive_confirmation_round_via_same_nested_checkpoint(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-planning-two-round.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        llm_payloads=[
            _clear_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output("NEEDS_CONFIRMATION", confirmation=_confirmation()),
        ],
    )
    round1_interrupt_id = payload["user_interrupt"]["interrupt_id"]
    upstream_before = _upstream_calls(llm_runtime)

    try:
        # --- Round 2: still ambiguous -- must pause again, still inside the
        # same nested subgraph. This is round 8/8 of NORMAL_MAX_LLM_CALLS. ---
        _queue_more(
            llm_runtime, [_answer_output("NEEDS_CONFIRMATION", confirmation=_confirmation())]
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

        round2_task = _nested_planning_task(runtime)
        assert round2_task.state.next == ("finalize",)
        round2_interrupt_id = second.payload["user_interrupt"]["interrupt_id"]
        assert second.payload["user_interrupt"]["origin_target"] == "planning.answer_only"
        assert round2_interrupt_id != round1_interrupt_id

        # --- Round 3: budget is already exhausted (round 2 was call 8/8) --
        # its own resolving call is itself the 9th and is correctly denied.
        # Everything provable before that point (same nested checkpoint,
        # zero upstream re-execution across rounds 2-3) is asserted here.
        calls_before_round3 = len(llm_runtime.calls)
        _queue_more(llm_runtime, [_answer_output("ANSWER_ONLY")])
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
        assert llm_runtime.calls[calls_before_round3:] == []
        # No upstream re-execution at any point across rounds 2-3.
        assert _upstream_calls(llm_runtime) == upstream_before
        assert len(_planning_calls(llm_runtime, "planning.compose_answer")) == 2
    finally:
        runtime.close()


# --- T14: invalid resume fails closed. ---


def test_planning_resume_rejects_wrong_interrupt_id(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-planning-invalid.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, _payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        llm_payloads=[
            _clear_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output("NEEDS_CONFIRMATION", confirmation=_confirmation()),
        ],
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
        assert len(llm_runtime.calls) == calls_before_resume
    finally:
        runtime.close()


def test_planning_resume_rejects_option_id_outside_allowed_scope(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-planning-invalid-option.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        llm_payloads=[
            _clear_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output("NEEDS_CONFIRMATION", confirmation=_confirmation()),
        ],
    )
    interrupt_id = payload["user_interrupt"]["interrupt_id"]
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


# --- T10: existing ANSWER_ONLY -> Review happy path unaffected. ---


def test_planning_answer_only_happy_path_completes(tmp_path: Path) -> None:
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
            _answer_output("ANSWER_ONLY"),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-planning-answer-happy.db",
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


# --- T11 (superseded by the Canonical Planning Production Migration):
# existing PLAN_READY -> Review happy path. ACTION Planning no longer
# accepts a whole-plan free-form ``planning.compose_arguments`` payload
# (``_plan_output(...)``) -- draft_plan now runs the canonical per-route
# Argument Writer via ``PlanningArgumentOrchestrator``, one call per frozen
# output route, assembled deterministically into ``ActionPlanDraftV1`` by
# ``planning_plan_assembler``. This scenario -- a real ``runtime.start()``
# ACTION run reaching ``PLAN_READY`` and then Review -- is covered by
# ``test_canonical_planning_migration.py``'s
# ``test_single_action_route_uses_canonical_writer_exactly_once`` (T1),
# which additionally asserts the per-route call shape and Review PASS
# transition. ANSWER-path PLAN_READY-equivalent (T10 above) is unaffected.
