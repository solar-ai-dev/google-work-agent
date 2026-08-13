"""Invocation and execution integration tests."""

from __future__ import annotations

from tests.integration.langgraph.test_runtime import (
    FIXTURE_ROOT,
    ActionPlanDraftV1,
    ApproveWriteActionCommand,
    ApproveWriteActionService,
    Callable,
    ClaimWriteActionCommand,
    FakeGoogleGateway,
    GoogleGatewayFault,
    GoogleGatewayFaultKind,
    Path,
    ProductFixtureSnapshotLoader,
    StoreWriteActionSuccessCommand,
    WorkflowCorrelationContext,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
    _action_required_intent,
    _ambiguous_intent,
    _analysis_output,
    _answer_output,
    _calendar_analysis_output,
    _calendar_intent,
    _calendar_selection_output,
    _clear_intent,
    _delete_task_write_plan_output,
    _delete_write_plan_output,
    _make_runtime,
    _plan,
    _read_plan_output,
    _review_output,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _send_write_plan_output,
    _start_read_request,
    _start_request,
    _start_write_request,
    _sufficiency_output,
    _write_plan_output,
    connect_sqlite,
    pytest,
    sqlite_unit_of_work_factory,
)


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
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
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
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[_ambiguous_intent()],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-confirm.db",
        prompt_manifest_path=manifest_path,
    )

    first = runtime.start(_start_request())

    assert first.outcome is WorkflowOutcome.ACCEPTED
    connection = connect_sqlite(database_path)
    try:
        run_row = connection.execute(
            "SELECT status, version FROM runs WHERE id = 'run-1';"
        ).fetchone()
        assert tuple(run_row) == ("WAITING_CONFIRMATION", 2)
    finally:
        connection.close()

    runtime.close()
    resumed_runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-confirm.db",
        prompt_manifest_path=manifest_path,
    )

    resumed = resumed_runtime.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="CONFIRMATION",
            resume_payload={
                "schema_version": 1,
                "response_kind": "FREE_TEXT",
                "selected_option_ids": [],
                "free_text": "I mean Kim from project alpha.",
            },
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
        run_row = connection.execute("SELECT status FROM runs WHERE id = 'run-1';").fetchone()
        assert run_row[0] == "COMPLETED"
        snapshot = resumed_runtime._graph.get_state(  # noqa: SLF001
            resumed_runtime._config_for_thread("thread-1")  # noqa: SLF001
        )
        request = snapshot.values["__request__"]
        assert request.request_text == "Please handle the follow-up."
        assert snapshot.values["prompt_context"]["confirmation_response"]["free_text"] == (
            "I mean Kim from project alpha."
        )
    finally:
        connection.close()
        resumed_runtime.close()


def test_langgraph_runtime_executes_verified_write_after_approval_resume(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _action_required_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
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
    approve_service = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1000,
    )
    approve_response = approve_service(
        ApproveWriteActionCommand(
            command_id="approve-1",
            request_hash="a" * 64,
            action_id="action-1",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-1",
            idempotency_key="b" * 64,
        )
    )
    assert approve_response.applied is True

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
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1') AS run_status,
                (SELECT status FROM actions WHERE id = 'action-1') AS action_status;
            """
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
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
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
    approved = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1000,
    )(
        ApproveWriteActionCommand(
            command_id="approve-before-restart",
            request_hash="e" * 64,
            action_id="action-1",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-before-restart",
            idempotency_key="f" * 64,
        )
    )
    assert approved.applied is True

    with sqlite_unit_of_work_factory(database_path)() as unit_of_work:
        unit_of_work.runs.set_verifying("run-1")
        unit_of_work.commit()
    runtime._preflight_write(action_id="action-1")  # noqa: SLF001
    claim = runtime._claim_write(  # noqa: SLF001
        ClaimWriteActionCommand(
            command_id="claim-before-restart",
            request_hash="1" * 64,
            action_id="action-1",
            expected_version=approved.action_version,
            source_snapshot={},
            attempt_id="attempt-before-restart",
            nonce="nonce-before-restart",
        )
    )
    assert claim.claim_token is not None
    executed = runtime._execute_write(  # noqa: SLF001
        action_id="action-1",
        claim_token=claim.claim_token,
    )
    runtime._store_write_success(  # noqa: SLF001
        StoreWriteActionSuccessCommand(
            command_id="store-before-restart",
            request_hash="2" * 64,
            action_id="action-1",
            attempt_id="attempt-before-restart",
            expected_action_version=claim.action_version,
            expected_attempt_version=0,
            snapshot=executed.snapshot,
        )
    )
    assert gateway.count_calls("create_task") == 1
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
            domain_status="VERIFYING",
            domain_version=3,
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
                (SELECT status FROM actions WHERE id = 'action-1'),
                (SELECT COUNT(*) FROM execution_attempts),
                (SELECT COUNT(*) FROM verifications);
            """
        ).fetchone()
        assert tuple(row) == ("COMPLETED", "VERIFIED", 1, 1)
    finally:
        connection.close()
        restarted.close()


@pytest.mark.parametrize(
    ("plan_output", "expected_operation", "calendar_context", "recovery_fault"),
    [
        (_send_write_plan_output, "send_gmail", False, None),
        (_delete_write_plan_output, "delete_calendar_event", True, None),
        (_delete_task_write_plan_output, "delete_task", False, None),
        (_send_write_plan_output, "send_gmail", False, GoogleGatewayFaultKind.HTTP_500),
    ],
)
def test_langgraph_runtime_executes_send_and_delete_after_approval_resume(
    tmp_path: Path,
    plan_output: Callable[[], ActionPlanDraftV1],
    expected_operation: str,
    calendar_context: bool,
    recovery_fault: GoogleGatewayFaultKind | None,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    llm_payloads = (
        [
            _calendar_intent(),
            [_plan("CALENDAR", {"calendar_id": "calendar-primary"})],
            _calendar_selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _calendar_analysis_output(),
            plan_output(),
            _review_output("PASS"),
        ]
        if calendar_context
        else [
            _action_required_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            plan_output(),
            _review_output("PASS"),
        ]
    )
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=llm_payloads,
        gateway=gateway,
        checkpoint_database_path=tmp_path / f"checkpoints-{expected_operation}.db",
        prompt_manifest_path=manifest_path,
    )

    started = runtime.start(_start_write_request())
    assert started.outcome is WorkflowOutcome.ACCEPTED
    approved = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1000,
    )(
        ApproveWriteActionCommand(
            command_id=f"approve-{expected_operation}",
            request_hash="c" * 64,
            action_id="action-1",
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
        row = connection.execute("SELECT status FROM actions WHERE id = 'action-1';").fetchone()
        assert row[0] == "VERIFIED"
        assert any(call.operation == expected_operation for call in gateway.call_log)
        if recovery_fault is not None:
            assert gateway.count_calls("send_gmail") == 1
            assert gateway.count_calls("search_by_recovery_fingerprint") == 1
    finally:
        connection.close()
        runtime.close()


def test_langgraph_runtime_executes_read_only_plan_to_terminal(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _action_required_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _read_plan_output(),
            _review_output("PASS"),
        ],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-read.db",
        prompt_manifest_path=manifest_path,
    )

    result = runtime.start(_start_read_request())

    assert result.outcome is WorkflowOutcome.COMPLETED
    connection = connect_sqlite(database_path)
    try:
        counts = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1') AS run_status,
                (SELECT status FROM actions WHERE id = 'action-read-1') AS action_status,
                (SELECT COUNT(*) FROM approvals) AS approval_count,
                (SELECT COUNT(*) FROM execution_attempts) AS attempt_count,
                (SELECT COUNT(*) FROM verifications) AS verification_count;
            """
        ).fetchone()
        assert tuple(counts) == ("COMPLETED", "VERIFIED", 0, 0, 0)
        assert any(call.operation == "get_task" for call in gateway.call_log)
    finally:
        connection.close()
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
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
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
