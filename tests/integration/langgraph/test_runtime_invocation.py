"""Invocation and execution integration tests."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Literal, cast

from tests.integration.langgraph.test_runtime import (
    FIXTURE_ROOT,
    ActionPlanDraftV1,
    ApproveWriteActionCommand,
    ApproveWriteActionService,
    Callable,
    ClaimWriteActionCommand,
    DeterministicUUID,
    FakeClockPort,
    FakeGoogleGateway,
    GoogleGatewayFault,
    GoogleGatewayFaultKind,
    GraphProfile,
    LangGraphWorkflowRuntime,
    McpConnectorWriteAdapter,
    Path,
    ProductFixtureSnapshotLoader,
    RequestIntentV2,
    StoreWriteActionSuccessCommand,
    WorkflowCorrelationContext,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
    _action_intent,
    _action_required_intent,
    _ambiguous_intent,
    _analysis_output,
    _answer_output,
    _calendar_analysis_output,
    _calendar_selection_output,
    _clear_intent,
    _delete_task_write_plan_output,
    _delete_write_plan_output,
    _gmail_analysis_output,
    _gmail_selection_output,
    _make_runtime,
    _QueuedLLMRuntime,
    _review_output,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _send_write_plan_output,
    _sole_persisted_action_id,
    _start_request,
    _start_write_request,
    _sufficiency_output,
    _tool_catalog,
    _write_plan_output,
    connect_sqlite,
    pytest,
    sqlite_unit_of_work_factory,
)
from tests.support.canonical_workflow_runtime import (
    resume_confirmation_with_handoff,
    start_with_admission,
)

from google_work_agent.application.use_cases.run.resume_run import (
    ResumeRunCommand,
    ResumeRunHandler,
)
from google_work_agent.ports import LLMErrorCode, LLMInvocationError, ResourceSnapshot


def test_langgraph_runtime_completes_answer_only_run(
    tmp_path: Path,
) -> None:
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
        checkpoint_database_path=tmp_path / "checkpoints-answer.db",
        prompt_manifest_path=manifest_path,
    )

    result = runtime.start(_start_request())

    assert result.outcome is WorkflowOutcome.COMPLETED
    connection = connect_sqlite(database_path)
    try:
        run_row = connection.execute(
            "SELECT status, version FROM runs WHERE id = 'run-1';"
        ).fetchone()
        message_count = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE run_id = 'run-1' AND role = 'ASSISTANT';"
        ).fetchone()[0]
        plan_count = connection.execute(
            "SELECT COUNT(*) FROM plans WHERE run_id = 'run-1';"
        ).fetchone()[0]
        assert tuple(run_row) == ("COMPLETED", 4)
        assert message_count == 1
        assert plan_count == 0
    finally:
        connection.close()
        runtime.close()


def test_langgraph_runtime_interrupts_for_confirmation_and_resumes_same_thread(
    tmp_path: Path,
) -> None:
    """I1: Request Understanding's NEEDS_CONFIRMATION now pauses via a real
    ``interrupt()`` called from *inside* the compiled ``request_understanding``
    nested subgraph (in its own ``finalize`` node), not the shared Main-Graph
    ``waiting_confirmation`` node. Resume must continue that same nested
    checkpoint -- ``init``/``classify`` (already completed before the pause)
    must NOT run again -- not restart the whole subgraph from START as the
    pre-I1 architecture did. A single final-result comparison cannot tell
    these two apart, so this test proves it via the actual checkpoint task
    hierarchy, Local State identity (``invocation_id``) held constant across
    the pause, and per-node call bookkeeping -- not just "the run completed".
    """
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[_ambiguous_intent()],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=database_path,
        prompt_manifest_path=manifest_path,
    )

    first = start_with_admission(runtime, database_path, _start_request())

    assert first.outcome is WorkflowOutcome.ACCEPTED
    connection = connect_sqlite(database_path)
    try:
        run_row = connection.execute(
            "SELECT status, langgraph_thread_id FROM runs WHERE id = 'run-1';"
        ).fetchone()
        assert run_row[0] == "WAITING_CONFIRMATION"
        thread_id_before = run_row[1]
    finally:
        connection.close()

    # Q4/E: the paused checkpoint's own task hierarchy proves WHERE the
    # interrupt actually lives -- not just that the thread_id is unchanged.
    thread_config = runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
    paused_snapshot = runtime._graph.get_state(thread_config, subgraphs=True)  # noqa: SLF001
    assert paused_snapshot.next == ("request_understanding",)
    assert len(paused_snapshot.tasks) == 1
    outer_task = paused_snapshot.tasks[0]
    assert outer_task.name == "request_understanding"
    nested_snapshot = outer_task.state
    # The canonical owner-local graph pauses at its explicit confirmation
    # node after goal identification and ambiguity detection have committed.
    assert nested_snapshot.next == ("confirm",)
    assert nested_snapshot.values["ru_candidate"]["goal"]

    # The API-facing paused-run projection (WorkflowInvocationResult.payload)
    # must still surface the confirmation question even though it never got
    # a chance to commit into the OUTER Main State's user_interrupt channel
    # (the nested subgraph never returned to the parent before pausing).
    assert first.payload["user_interrupt"] is not None
    interrupt_id = first.payload["user_interrupt"]["interrupt_id"]
    assert first.payload["user_interrupt"]["origin_target"] == "request_understanding.classify"

    runtime.close()
    # Reconnect with a fresh runtime instance sharing the same checkpoint DB
    # (simulating a process restart) so the test can inspect a fresh
    # `.calls` log and prove nothing from before the pause is replayed.
    resumed_llm_runtime = _QueuedLLMRuntime(
        [
            _clear_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
            _review_output("PASS"),
        ]
    )
    resumed_gateway = FakeGoogleGateway(snapshot)
    resumed_runtime = LangGraphWorkflowRuntime(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        llm_runtime=resumed_llm_runtime,
        gateway=resumed_gateway,
        connector_execution=McpConnectorWriteAdapter(gateway=resumed_gateway),
        tool_catalog=_tool_catalog(),
        now_ms=FakeClockPort(1000).now_ms,
        id_factory=DeterministicUUID(prefix="runtime").next_id,
        signing_secret="stage17-secret",
        service_instance_id="stage17-service",
        checkpoint_database_path=database_path,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
        default_tasklist_id_provider=lambda: "task-list-default",
    )

    # G3 Final Closure budget accounting (docs/06 SS11, docs/15 SS8.2) is
    # unchanged by I1: the SAME real semantic work has to happen either way
    # -- one more classify-shaped call to resolve the ambiguity, then
    # tool_route/plan_query/select_evidence/assess_sufficiency/analyze/
    # answer_only for the first time (Request Understanding had not
    # completed before the pause, so nothing downstream had run yet, in
    # either architecture). 1 (pre-pause) + 7 (post-resume) = 8, exactly
    # NORMAL_MAX_LLM_CALLS. The resolved answer_draft is ANSWER_ONLY, so
    # Planning->Review is the Canonical ANSWER_ONLY->Response Synthesis edge
    # (canonical_response_runtime.canonicalize_answer_only_decision,
    # docs/design/06-agent-workflow.md "Planning ANSWER_ONLY -> Response
    # Synthesis") -- Review is never dispatched, so the run completes at
    # exactly the 8-call cap instead of a 9th (review) call being denied.
    # The unchanged 7-call count below proves I1 did not silently change
    # RunBudgetV1 behavior while replacing the resume mechanism.
    resume_payload = {
        "schema_version": 1,
        "interrupt_id": interrupt_id,
        "response_kind": "FREE_TEXT",
        "selected_option": None,
        "free_text": "I mean Kim from project alpha.",
    }
    application_result, resumed = resume_confirmation_with_handoff(
        resumed_runtime,
        database_path,
        resume_payload=resume_payload,
        command_id="command-2",
    )
    assert application_result.applied is True
    assert resumed is not None
    result = cast(Any, resumed)
    assert result.outcome is WorkflowOutcome.COMPLETED
    assert len(resumed_llm_runtime.calls) == 7

    # Exactly one more real Provider call resolves the ambiguity -- not a
    # second traversal of the "classify" *node* the way the pre-I1
    # architecture's full-subgraph-restart resume required.
    classify_calls = [
        call
        for call in resumed_llm_runtime.calls
        if getattr(call["prompt_ref"], "prompt_id", None) == "request_understanding.classify"
    ]
    assert len(classify_calls) == 1
    classify_prompt_input = cast(dict[str, object], classify_calls[0]["prompt_input"])

    # Prompt resume boundary (15 SS10-11): only the bounded
    # ConfirmationResponseV1 crosses into the Product Prompt input -- no raw
    # resume payload, interrupt_id, checkpoint metadata, or
    # AgentNodeResumeTargetV2. classify's own input shape is exactly
    # {user_request, entry_mode, language, selected_resources,
    # confirmation_response} (_prompt_input_from_request) -- assert both the
    # bounded value is present and every disallowed field is absent.
    assert classify_prompt_input["confirmation_response"] == {
        "schema_version": 1,
        "response_kind": "FREE_TEXT",
        "selected_option": None,
        "free_text": "I mean Kim from project alpha.",
    }
    for forbidden_key in ("interrupt_id", "resume_target", "checkpoint", "owner_subgraph"):
        assert forbidden_key not in classify_prompt_input

    connection = connect_sqlite(database_path)
    try:
        run_row = connection.execute(
            "SELECT status, langgraph_thread_id FROM runs WHERE id = 'run-1';"
        ).fetchone()
        assert run_row[0] == "COMPLETED"
        # same run_id + same langgraph_thread_id end to end.
        assert run_row[1] == thread_id_before == "thread-1"
    finally:
        connection.close()
        resumed_runtime.close()


def _nested_request_understanding_task(runtime: LangGraphWorkflowRuntime) -> Any:
    """The paused checkpoint's own task for the nested request_understanding
    subgraph -- asserting on this (rather than only on the final result) is
    what actually distinguishes "same nested checkpoint resume" from a full
    subgraph restart that happens to produce the same final answer."""
    thread_config = runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
    snapshot = runtime._graph.get_state(thread_config, subgraphs=True)  # noqa: SLF001
    assert snapshot.next == ("request_understanding",)
    assert len(snapshot.tasks) == 1
    outer_task = snapshot.tasks[0]
    assert outer_task.name == "request_understanding"
    return outer_task


def _resume_through_application(
    *,
    runtime: LangGraphWorkflowRuntime,
    database_path: Path,
    resume_payload: dict[str, object],
    resume_kind: str,
    command_id: str,
) -> tuple[object, object | None]:
    if resume_kind == "CONFIRMATION":
        return resume_confirmation_with_handoff(
            runtime,
            database_path,
            resume_payload=resume_payload,
            command_id=command_id,
        )
    with sqlite_unit_of_work_factory(database_path)() as unit_of_work:
        run = unit_of_work.runs.get_by_id("run-1")
        assert run is not None
        expected_run_version = run.version
    runtime_results: list[object] = []

    def enqueue_resume(**queued: object) -> None:
        runtime_results.append(
            runtime.resume(
                WorkflowResumeRequest(
                    run_id=str(queued["run_id"]),
                    workflow_key="thread-1",
                    resume_kind=str(queued["resume_kind"]),
                    resume_payload=dict(queued["resume_payload"]),  # type: ignore[arg-type]
                    correlation=WorkflowCorrelationContext(
                        request_id=str(queued["request_id"]),
                        command_id=str(queued["command_id"]),
                        api_contract_version="1",
                    ),
                )
            )
        )

    handler = ResumeRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=FakeClockPort(2000).now_ms,
        enqueue_resume=enqueue_resume,
        resolve_resume_authority=lambda **kwargs: runtime.resolve_resume_authority(
            run_id=str(kwargs["run_id"]),
            workflow_key="thread-1",
            resume_kind=str(kwargs["resume_kind"]),
        ),
    )
    application_result = handler(
        ResumeRunCommand(
            command_id=command_id,
            request_hash=sha256(command_id.encode("utf-8")).hexdigest(),
            run_id="run-1",
            expected_run_version=expected_run_version,
            resume_kind=resume_kind,
            api_contract_version="1",
        ),
        request_id=f"request-{command_id}",
        resume_payload=resume_payload,
    )
    return application_result, runtime_results[0] if runtime_results else None


def test_langgraph_runtime_resumes_second_consecutive_confirmation_round_via_same_nested_checkpoint(
    tmp_path: Path,
) -> None:
    """I1 follow-up: a resolved-but-still-ambiguous confirmation answer must
    trigger a SECOND real nested interrupt/resume inside Request
    Understanding's own subgraph (a fresh "finalize" task via its
    conditional self-loop edge) -- not a fall back to the shared Main-Graph
    owner-restart mechanism, and not a second interrupt() call replayed
    inside the same already-resumed task (which would silently re-run the
    round-1 Provider call and Domain write). Proves the full
    NEEDS_CONFIRMATION -> response -> NEEDS_CONFIRMATION -> response ->
    COMPLETE cycle stays on the same run_id/thread_id/owner, with init and
    classify never re-entered as separate tasks for either round.
    """
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    # --- Round 1: start, pause on the first ambiguity. ---
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[_ambiguous_intent()],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=database_path,
        prompt_manifest_path=manifest_path,
    )
    first = start_with_admission(runtime, database_path, _start_request())
    assert first.outcome is WorkflowOutcome.ACCEPTED
    round1_task = _nested_request_understanding_task(runtime)
    assert round1_task.state.next == ("confirm",)
    assert round1_task.state.values["ru_candidate"]["goal"]
    round1_interrupt_id = first.payload["user_interrupt"]["interrupt_id"]
    assert first.payload["user_interrupt"]["origin_target"] == "request_understanding.classify"
    runtime.close()

    # --- Round 2: resume round 1's answer, but the reclassify is ITSELF
    # still ambiguous. This must pause again, still inside the same nested
    # subgraph -- proving the self-loop (not a shared-path fallback) fired.
    round2_llm_runtime = _QueuedLLMRuntime([_ambiguous_intent()])
    round2_gateway = FakeGoogleGateway(snapshot)
    round2_runtime = LangGraphWorkflowRuntime(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        llm_runtime=round2_llm_runtime,
        gateway=round2_gateway,
        connector_execution=McpConnectorWriteAdapter(gateway=round2_gateway),
        tool_catalog=_tool_catalog(),
        now_ms=FakeClockPort(1000).now_ms,
        id_factory=DeterministicUUID(prefix="round2").next_id,
        signing_secret="stage17-secret",
        service_instance_id="stage17-service",
        checkpoint_database_path=database_path,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
        default_tasklist_id_provider=lambda: "task-list-default",
    )
    application_result, second = _resume_through_application(
        runtime=round2_runtime,
        database_path=database_path,
        resume_payload={
            "schema_version": 1,
            "interrupt_id": round1_interrupt_id,
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": "round-1 answer, still ambiguous apparently.",
        },
        resume_kind="CONFIRMATION",
        command_id="command-2",
    )
    assert application_result.applied is True  # type: ignore[attr-defined]
    assert second is not None
    # A second real pause, NOT an error and NOT the run silently completing.
    assert second.outcome is WorkflowOutcome.ACCEPTED
    # Exactly the one round-1 reclassify call happened in this instance --
    # no re-entry of "classify" as a node, no restart of tool_route etc.
    assert len(round2_llm_runtime.calls) == 1
    round1_reclassify_input = cast(dict[str, object], round2_llm_runtime.calls[0]["prompt_input"])
    round1_reclassify_response = cast(
        dict[str, object], round1_reclassify_input["confirmation_response"]
    )
    assert round1_reclassify_response["free_text"] == "round-1 answer, still ambiguous apparently."

    round2_task = _nested_request_understanding_task(round2_runtime)
    # Still "finalize" pending -- the self-loop re-entered "finalize" as a
    # fresh task for round 2, it did not fall back through
    # init -> classify -> finalize (which "next" would show as ("init",) or
    # ("classify",) immediately after a resume, not "finalize").
    assert round2_task.state.next == ("confirm",)
    assert round2_task.state.values["ru_candidate"]["goal"]
    round2_interrupt_id = second.payload["user_interrupt"]["interrupt_id"]
    assert second.payload["user_interrupt"]["origin_target"] == "request_understanding.classify"
    # A genuinely new interrupt instance for round 2, not a stale replay of
    # round 1's.
    assert round2_interrupt_id != round1_interrupt_id
    round2_runtime.close()

    # --- Round 3: resume round 2's answer with a resolved (non-ambiguous)
    # reclassify -- Request Understanding completes and the run proceeds
    # into the downstream pipeline for the first time.
    round3_llm_runtime = _QueuedLLMRuntime(
        [
            _clear_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
            _review_output("PASS"),
        ]
    )
    round3_gateway = FakeGoogleGateway(snapshot)
    round3_runtime = LangGraphWorkflowRuntime(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        llm_runtime=round3_llm_runtime,
        gateway=round3_gateway,
        connector_execution=McpConnectorWriteAdapter(gateway=round3_gateway),
        tool_catalog=_tool_catalog(),
        now_ms=FakeClockPort(1000).now_ms,
        id_factory=DeterministicUUID(prefix="round3").next_id,
        signing_secret="stage17-secret",
        service_instance_id="stage17-service",
        checkpoint_database_path=database_path,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
        default_tasklist_id_provider=lambda: "task-list-default",
    )
    # G3 budget accounting is cumulative across all 3 resumes on this one
    # Run (RunBudgetV1 is Domain-persisted, not per-invocation): classify +
    # round-1 reclassify + round-2 reclassify + tool_route + plan_query +
    # select_evidence + assess_sufficiency + analyze = 8, exactly
    # NORMAL_MAX_LLM_CALLS, so answer_only (the 9th) is correctly denied --
    # two confirmation rounds cost real budget like any other real call,
    # with no special exemption.
    with pytest.raises(LLMInvocationError) as excinfo:
        _resume_through_application(
            runtime=round3_runtime,
            database_path=database_path,
            resume_payload={
                "schema_version": 1,
                "interrupt_id": round2_interrupt_id,
                "response_kind": "FREE_TEXT",
                "selected_option": None,
                "free_text": "round-2 answer, resolves it.",
            },
            resume_kind="CONFIRMATION",
            command_id="command-3",
        )
    assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED
    assert len(round3_llm_runtime.calls) == 6

    round2_reclassify_input = cast(dict[str, object], round3_llm_runtime.calls[0]["prompt_input"])
    round2_reclassify_response = cast(
        dict[str, object], round2_reclassify_input["confirmation_response"]
    )
    assert round2_reclassify_response["free_text"] == "round-2 answer, resolves it."

    connection = connect_sqlite(database_path)
    try:
        run_row = connection.execute(
            "SELECT status, langgraph_thread_id FROM runs WHERE id = 'run-1';"
        ).fetchone()
        # Forward progress happened (past WAITING_CONFIRMATION) but the run
        # never reached COMPLETED -- same run_id + same thread_id throughout.
        assert run_row[0] not in {"COMPLETED", "WAITING_CONFIRMATION"}
        assert run_row[1] == "thread-1"
    finally:
        connection.close()
        round3_runtime.close()


def test_langgraph_runtime_executes_verified_write_after_approval_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
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
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-write.db",
        prompt_manifest_path=manifest_path,
    )

    started = runtime.start(_start_write_request())

    assert started.outcome is WorkflowOutcome.ACCEPTED
    action_id = _sole_persisted_action_id(database_path)
    approve_service = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1000,
    )
    approve_response = approve_service(
        ApproveWriteActionCommand(
            command_id="approve-1",
            request_hash="a" * 64,
            action_id=action_id,
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-1",
            idempotency_key="b" * 64,
        )
    )
    assert approve_response.applied is True

    observed_run_statuses: dict[str, str] = {}
    original_create_task = gateway.create_task
    original_get_task = gateway.get_task

    def current_run_status() -> str:
        connection = connect_sqlite(database_path)
        try:
            return str(
                connection.execute("SELECT status FROM runs WHERE id = 'run-1';").fetchone()[0]
            )
        finally:
            connection.close()

    def create_task_with_status_observation(
        *,
        task_list_id: str,
        payload: dict[str, object],
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        observed_run_statuses["write"] = current_run_status()
        return original_create_task(
            task_list_id=task_list_id,
            payload=payload,
            claim_context=claim_context,
        )

    def get_task_with_status_observation(*, task_list_id: str, task_id: str) -> ResourceSnapshot:
        observed_run_statuses["verification"] = current_run_status()
        return original_get_task(task_list_id=task_list_id, task_id=task_id)

    monkeypatch.setattr(gateway, "create_task", create_task_with_status_observation)
    monkeypatch.setattr(gateway, "get_task", get_task_with_status_observation)

    resumed = runtime.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="APPROVAL",
            resume_payload={"approved": True},
            correlation=WorkflowCorrelationContext(
                request_id="request-2",
                command_id="command-2",
                api_contract_version="1",
            ),
        )
    )

    assert resumed.outcome is WorkflowOutcome.COMPLETED
    assert observed_run_statuses == {
        "write": "WAITING_APPROVAL",
        "verification": "VERIFYING",
    }
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1') AS run_status,
                (SELECT status FROM actions WHERE id = ?) AS action_status;
            """,
            (action_id,),
        ).fetchone()
        verification_count = connection.execute("SELECT COUNT(*) FROM verifications;").fetchone()[0]
        assert tuple(row) == ("COMPLETED", "VERIFIED")
        assert verification_count == 1
        assert any(call.operation == "create_task" for call in gateway.call_log)
        assert any(call.operation == "get_task" for call in gateway.call_log)
    finally:
        connection.close()
        runtime.close()


def test_langgraph_runtime_restart_verifies_executed_action_without_replaying_write(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    checkpoint_path = tmp_path / "checkpoints-executed-restart.db"
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
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
        gateway=gateway,
        checkpoint_database_path=checkpoint_path,
        prompt_manifest_path=manifest_path,
    )
    assert runtime.start(_start_write_request()).outcome is WorkflowOutcome.ACCEPTED
    action_id = _sole_persisted_action_id(database_path)
    approved = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1000,
    )(
        ApproveWriteActionCommand(
            command_id="approve-before-restart",
            request_hash="e" * 64,
            action_id=action_id,
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-before-restart",
            idempotency_key="f" * 64,
        )
    )
    assert approved.applied is True

    runtime._preflight_write(action_id=action_id)  # noqa: SLF001
    claim = runtime._claim_write(  # noqa: SLF001
        ClaimWriteActionCommand(
            command_id="claim-before-restart",
            request_hash="1" * 64,
            action_id=action_id,
            expected_version=approved.action_version,
            source_snapshot={},
            attempt_id="attempt-before-restart",
            nonce="nonce-before-restart",
        )
    )
    assert claim.claim_token is not None
    executed = runtime._execute_write(  # noqa: SLF001
        action_id=action_id,
        claim_token=claim.claim_token,
    )
    runtime._store_write_success(  # noqa: SLF001
        StoreWriteActionSuccessCommand(
            command_id="store-before-restart",
            request_hash="2" * 64,
            action_id=action_id,
            attempt_id="attempt-before-restart",
            expected_action_version=claim.action_version,
            expected_attempt_version=0,
            snapshot=executed.snapshot,
        )
    )
    assert gateway.count_calls("create_task") == 1
    connection = connect_sqlite(database_path)
    try:
        interrupted_state = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1'),
                (SELECT status FROM actions WHERE id = ?);
            """,
            (action_id,),
        ).fetchone()
        assert tuple(interrupted_state) == ("WAITING_APPROVAL", "EXECUTED")
    finally:
        connection.close()
    runtime.close()

    restarted = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=checkpoint_path,
        prompt_manifest_path=manifest_path,
    )
    recovered = restarted.recover_open_run(
        WorkflowRecoveryRequest(
            run_id="run-1",
            workflow_key="thread-1",
            domain_status="WAITING_APPROVAL",
            domain_version=2,
            correlation=WorkflowCorrelationContext(
                request_id="startup-recovery",
                command_id=None,
                api_contract_version="1",
            ),
        )
    )

    assert recovered.outcome is WorkflowOutcome.COMPLETED
    assert gateway.count_calls("create_task") == 1
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1'),
                (SELECT status FROM actions WHERE id = ?),
                (SELECT COUNT(*) FROM execution_attempts),
                (SELECT COUNT(*) FROM verifications);
            """,
            (action_id,),
        ).fetchone()
        assert tuple(row) == ("COMPLETED", "VERIFIED", 1, 1)
    finally:
        connection.close()
        restarted.close()


def test_verification_auth_expired_reauths_and_resumes_to_verified_without_replaying_write(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    checkpoint_path = tmp_path / "checkpoints-verify-reauth.db"
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
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
        gateway=gateway,
        checkpoint_database_path=checkpoint_path,
        prompt_manifest_path=manifest_path,
    )
    assert runtime.start(_start_write_request()).outcome is WorkflowOutcome.ACCEPTED
    action_id = _sole_persisted_action_id(database_path)
    approved = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1000,
    )(
        ApproveWriteActionCommand(
            command_id="approve-before-verify-reauth",
            request_hash="e" * 64,
            action_id=action_id,
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-before-verify-reauth",
            idempotency_key="f" * 64,
        )
    )
    assert approved.applied is True

    # A. Resuming the pending "waiting_approval" interrupt drives the real
    # action_execution graph node. The write succeeds, then the
    # Verification GET hits AUTH_EXPIRED.
    gateway.queue_fault(
        operation="get_task",
        fault=GoogleGatewayFault(kind=GoogleGatewayFaultKind.HTTP_401),
    )
    approval_resumed = runtime.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="APPROVAL",
            resume_payload={"approved": True},
            correlation=WorkflowCorrelationContext(
                request_id="approval-resume-request",
                command_id="approval-resume-command",
                api_contract_version="1",
            ),
        )
    )
    assert approval_resumed.outcome is WorkflowOutcome.ACCEPTED
    assert approval_resumed.payload["run_status"] == "REAUTH_REQUIRED"
    assert gateway.count_calls("create_task") == 1

    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1'),
                (SELECT status FROM actions WHERE id = ?),
                (SELECT COUNT(*) FROM verifications);
            """,
            (action_id,),
        ).fetchone()
        assert tuple(row) == ("REAUTH_REQUIRED", "EXECUTED", 0)
    finally:
        connection.close()

    # B. Reauth completes; resume re-attempts Verification only (the fault
    # queue is one-shot, so the retried GET now succeeds) and reaches
    # VERIFIED / COMPLETED.
    application_result, resumed = _resume_through_application(
        runtime=runtime,
        database_path=database_path,
        resume_payload={},
        resume_kind="REAUTH_COMPLETED",
        command_id="reauth-resume-command",
    )
    assert application_result.applied is True  # type: ignore[attr-defined]
    assert resumed is None
    recovery_result, resumed = _resume_through_application(
        runtime=runtime,
        database_path=database_path,
        resume_payload={},
        resume_kind="RECOVERY_RECHECK",
        command_id="verification-recovery-recheck-command",
    )
    assert recovery_result.applied is True  # type: ignore[attr-defined]
    assert resumed is not None
    assert resumed.outcome is WorkflowOutcome.COMPLETED

    # C. The write was never replayed -- exactly one create_task call total,
    # across both the original attempt and the reauth resume.
    assert gateway.count_calls("create_task") == 1
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1'),
                (SELECT status FROM actions WHERE id = ?),
                (SELECT COUNT(*) FROM execution_attempts),
                (SELECT COUNT(*) FROM verifications);
            """,
            (action_id,),
        ).fetchone()
        assert tuple(row) == ("COMPLETED", "VERIFIED", 1, 1)
    finally:
        connection.close()
        runtime.close()


def test_recovery_unknown_auth_expired_reauths_and_resumes_without_replaying_write(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    checkpoint_path = tmp_path / "checkpoints-recovery-reauth.db"
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
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
        gateway=gateway,
        checkpoint_database_path=checkpoint_path,
        prompt_manifest_path=manifest_path,
    )
    assert runtime.start(_start_write_request()).outcome is WorkflowOutcome.ACCEPTED
    action_id = _sole_persisted_action_id(database_path)
    approved = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1000,
    )(
        ApproveWriteActionCommand(
            command_id="approve-recovery-reauth",
            request_hash="a" * 64,
            action_id=action_id,
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-recovery-reauth",
            idempotency_key="b" * 64,
        )
    )
    assert approved.applied is True

    # A. The write itself actually reaches the provider (the fake gateway
    # records the created task before raising) but the client-side response
    # is lost, so the Action lands on UNKNOWN_RESULT and the Run moves to
    # RECOVERY_REQUIRED. The same resume call auto-continues into recovery,
    # where the recovery search itself now hits AUTH_EXPIRED.
    gateway.queue_fault(
        operation="create_task",
        fault=GoogleGatewayFault(kind=GoogleGatewayFaultKind.HTTP_500),
    )
    gateway.queue_fault(
        operation="search_by_recovery_fingerprint",
        fault=GoogleGatewayFault(kind=GoogleGatewayFaultKind.HTTP_401),
    )
    approval_resumed = runtime.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="APPROVAL",
            resume_payload={"approved": True},
            correlation=WorkflowCorrelationContext(
                request_id="approval-resume-recovery-reauth",
                command_id="approval-resume-recovery-reauth-command",
                api_contract_version="1",
            ),
        )
    )
    assert approval_resumed.outcome is WorkflowOutcome.ACCEPTED
    assert approval_resumed.payload["run_status"] == "REAUTH_REQUIRED"
    assert gateway.count_calls("create_task") == 1
    # The fake gateway's fault-raising branch for this operation does not
    # append to call_log (only its success path does), so the failed
    # AUTH_EXPIRED attempt is invisible to count_calls here by construction.
    assert gateway.count_calls("search_by_recovery_fingerprint") == 0

    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1'),
                (SELECT status FROM actions WHERE id = ?);
            """,
            (action_id,),
        ).fetchone()
        assert tuple(row) == ("REAUTH_REQUIRED", "UNKNOWN_RESULT")
    finally:
        connection.close()

    # B. Reauth completes; resume re-enters recover_unknown via the same
    # domain-facts continuation the crash-restart path uses (the still
    # unresolved UNKNOWN_RESULT action, not Run status, drives re-entry).
    # The fault queue is one-shot, so the retried search now succeeds,
    # finds the already-created task, and reaches VERIFIED/COMPLETED
    # without ever calling create_task again.
    application_result, resumed = _resume_through_application(
        runtime=runtime,
        database_path=database_path,
        resume_payload={},
        resume_kind="REAUTH_COMPLETED",
        command_id="reauth-resume-recovery-reauth-command",
    )
    assert application_result.applied is True  # type: ignore[attr-defined]
    assert resumed is None
    recovery_result, resumed = _resume_through_application(
        runtime=runtime,
        database_path=database_path,
        resume_payload={},
        resume_kind="RECOVERY_RECHECK",
        command_id="unknown-recovery-recheck-command",
    )
    assert recovery_result.applied is True  # type: ignore[attr-defined]
    assert resumed is not None
    assert resumed.outcome is WorkflowOutcome.COMPLETED

    # C. The write was never replayed -- exactly one create_task call total,
    # across both the original attempt and the reauth resume. The retried
    # search now succeeds (fault queue exhausted), so it is the first call
    # to actually reach call_log.
    assert gateway.count_calls("create_task") == 1
    assert gateway.count_calls("search_by_recovery_fingerprint") == 1
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1'),
                (SELECT status FROM actions WHERE id = ?),
                (SELECT COUNT(*) FROM execution_attempts),
                (SELECT COUNT(*) FROM verifications);
            """,
            (action_id,),
        ).fetchone()
        assert tuple(row) == ("COMPLETED", "VERIFIED", 1, 1)
    finally:
        connection.close()
        runtime.close()


def test_langgraph_runtime_restart_reconciles_a_claim_stalled_before_dispatch(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    checkpoint_path = tmp_path / "checkpoints-claim-stalled-restart.db"
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
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
        gateway=gateway,
        checkpoint_database_path=checkpoint_path,
        prompt_manifest_path=manifest_path,
    )
    assert runtime.start(_start_write_request()).outcome is WorkflowOutcome.ACCEPTED
    action_id = _sole_persisted_action_id(database_path)
    approved = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1000,
    )(
        ApproveWriteActionCommand(
            command_id="approve-before-claim-stall",
            request_hash="e" * 64,
            action_id=action_id,
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-before-claim-stall",
            idempotency_key="f" * 64,
        )
    )
    assert approved.applied is True

    # Claim commits (Action -> EXECUTING, Attempt -> CLAIMED), then the
    # process is simulated to crash before ExecuteWriteActionService (or
    # any terminal execution result) ever runs -- dispatch's delivery is
    # genuinely unknown, not "not sent".
    runtime._preflight_write(action_id=action_id)  # noqa: SLF001
    claim = runtime._claim_write(  # noqa: SLF001
        ClaimWriteActionCommand(
            command_id="claim-before-stall",
            request_hash="1" * 64,
            action_id=action_id,
            expected_version=approved.action_version,
            source_snapshot={},
            attempt_id="attempt-before-stall",
            nonce="nonce-before-stall",
        )
    )
    assert claim.claim_token is not None
    assert gateway.count_calls("create_task") == 0

    connection = connect_sqlite(database_path)
    try:
        stalled_state = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1'),
                (SELECT status FROM actions WHERE id = ?),
                (SELECT status FROM execution_attempts WHERE id = 'attempt-before-stall');
            """,
            (action_id,),
        ).fetchone()
        assert tuple(stalled_state) == ("WAITING_APPROVAL", "EXECUTING", "CLAIMED")
    finally:
        connection.close()
    runtime.close()

    restarted = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=checkpoint_path,
        prompt_manifest_path=manifest_path,
    )
    recovered = restarted.recover_open_run(
        WorkflowRecoveryRequest(
            run_id="run-1",
            workflow_key="thread-1",
            domain_status="WAITING_APPROVAL",
            domain_version=2,
            correlation=WorkflowCorrelationContext(
                request_id="startup-recovery-claim-stall",
                command_id=None,
                api_contract_version="1",
            ),
        )
    )

    # The run is no longer silently stalled: it reached a real, actionable
    # Recovery outcome, and the write was never blindly retried/replayed.
    assert recovered.outcome is WorkflowOutcome.RECOVERY_REQUIRED
    assert gateway.count_calls("create_task") == 0
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1'),
                (SELECT status FROM actions WHERE id = ?),
                (SELECT status FROM execution_attempts WHERE id = 'attempt-before-stall'),
                (SELECT COUNT(*) FROM execution_attempts);
            """,
            (action_id,),
        ).fetchone()
        assert tuple(row) == ("RECOVERY_REQUIRED", "UNKNOWN_RESULT", "UNKNOWN_RESULT", 1)
    finally:
        connection.close()
        restarted.close()


@pytest.mark.parametrize(
    ("plan_output", "expected_operation", "context_family", "recovery_fault", "intent"),
    [
        (
            _send_write_plan_output,
            "send_gmail",
            "GMAIL",
            None,
            _action_intent(resource="GMAIL_MESSAGE", effect="SEND"),
        ),
        (
            _delete_write_plan_output,
            "delete_calendar_event",
            "CALENDAR",
            None,
            _action_intent(
                resource="CALENDAR_EVENT",
                effect="DELETE",
                source="CALENDAR",
            ),
        ),
        (
            _delete_task_write_plan_output,
            "delete_task",
            "TASKS",
            None,
            _action_intent(resource="TASK", effect="DELETE"),
        ),
        (
            _send_write_plan_output,
            "send_gmail",
            "GMAIL",
            GoogleGatewayFaultKind.HTTP_500,
            _action_intent(resource="GMAIL_MESSAGE", effect="SEND"),
        ),
    ],
)
def test_langgraph_runtime_executes_send_and_delete_after_approval_resume(
    tmp_path: Path,
    plan_output: Callable[[], ActionPlanDraftV1],
    expected_operation: str,
    context_family: Literal["TASKS", "GMAIL", "CALENDAR"],
    recovery_fault: GoogleGatewayFaultKind | None,
    intent: RequestIntentV2,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    if context_family == "CALENDAR":
        context_payloads = [
            _calendar_selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _calendar_analysis_output(),
        ]
    elif context_family == "GMAIL":
        context_payloads = [
            _gmail_selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _gmail_analysis_output(),
        ]
    else:
        context_payloads = [
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
        ]
    llm_payloads = [intent, *context_payloads, plan_output(), _review_output("PASS")]
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=llm_payloads,
        gateway=gateway,
        checkpoint_database_path=tmp_path / f"checkpoints-{expected_operation}.db",
        prompt_manifest_path=manifest_path,
    )

    started = runtime.start(_start_write_request())
    assert started.outcome is WorkflowOutcome.ACCEPTED
    action_id = _sole_persisted_action_id(database_path)
    approved = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1000,
    )(
        ApproveWriteActionCommand(
            command_id=f"approve-{expected_operation}",
            request_hash="c" * 64,
            action_id=action_id,
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id=f"approval-{expected_operation}",
            idempotency_key="d" * 64,
        )
    )
    assert approved.applied is True
    if recovery_fault is not None:
        gateway.queue_fault(
            operation=expected_operation,
            fault=GoogleGatewayFault(recovery_fault),
        )

    resumed = runtime.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="APPROVAL",
            resume_payload={"approved": True},
            correlation=WorkflowCorrelationContext(
                request_id="request-2",
                command_id="command-2",
                api_contract_version="1",
            ),
        )
    )

    assert resumed.outcome is WorkflowOutcome.COMPLETED
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            "SELECT status FROM actions WHERE id = ?;", (action_id,)
        ).fetchone()
        assert row[0] == "VERIFIED"
        assert any(call.operation == expected_operation for call in gateway.call_log)
        if recovery_fault is not None:
            assert gateway.count_calls("send_gmail") == 1
            assert gateway.count_calls("search_by_recovery_fingerprint") == 1
    finally:
        connection.close()
        runtime.close()

        # test_langgraph_runtime_executes_read_only_plan_to_terminal (superseded by
        # the Canonical Planning Production Migration): this scenario paired an
        # ACTION-mode intent (Tool Route always freezes a write output route for
        # ``_action_required_intent()``) with a legacy Planning LLM output that
        # unilaterally downgraded the plan to a single READ action with no writes
        # at all. Legacy ``_validate_frozen_output_routes`` allowed this (it only
        # checks non-READ actions against ``output_routes``, so an all-READ plan
        # skipped that check entirely) -- effectively letting Planning override
        # Tool Route's frozen write decision. Canonical Planning has no such
        # authority: ``PlanningArgumentOrchestrator``/``planning_plan_assembler``
        # always produce exactly one action per frozen output route
        # (``materialize_action_seeds`` requires an exact 1:1 route<->candidate
        # pairing), and ``determine_semantic_routes`` never freezes a READ output
        # route (ACTION mode is only entered when a write effect hint is present).
        # A "plan whose only action is READ reaches COMPLETED with zero
        # approvals/writes" is therefore only reachable when Tool Route itself
        # never freezes an output route in the first place -- i.e. genuinely
        # read-only requests belong to the ANSWER path, which is unaffected by
        # this migration and already covered elsewhere in this suite.
        runtime.close()


def test_langgraph_runtime_supports_same_database_for_domain_and_checkpointer(
    tmp_path: Path,
) -> None:
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
        checkpoint_database_path=database_path,
        prompt_manifest_path=manifest_path,
    )

    result = runtime.start(_start_request())

    assert result.outcome is WorkflowOutcome.COMPLETED
    connection = connect_sqlite(database_path)
    try:
        checkpoint_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'checkpoints%';"
            ).fetchall()
        }
        assert checkpoint_tables
    finally:
        connection.close()
        runtime.close()
