"""UNKNOWN_RESULT and recovery integration tests."""

# ruff: noqa: F401

from __future__ import annotations

from json import loads as _loads

from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESUME_CONTRACT_VERSION,
)
from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.application.use_cases.action.prepare_write_retry import (
    PrepareWriteRetryCommand,
    PrepareWriteRetryHandler,
)
from google_work_agent.application.use_cases.recovery.resolve_recovery import (
    ResolveRecoveryCommandV1,
    ResolveRecoveryHandler,
)
from google_work_agent.domain.recovery.model import RecoveryResolution
from tests.integration.persistence.test_action_reject_vertical_slice import (
    _service as _seed_workflow_checkpoint,
)
from tests.integration.persistence.test_write_actions import (
    DeliveryCertainty,
    ExecuteWriteActionService,
    FakeClockPort,
    FakeGoogleGateway,
    GoogleGatewayFault,
    GoogleGatewayFaultKind,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGateway,
    GoogleWorkspaceGatewayError,
    MarkWriteActionUnknownResultCommand,
    MarkWriteActionUnknownResultService,
    Path,
    RecoverUnknownCreateActionCommand,
    RecoverUnknownCreateActionService,
    RecoverUnknownDeleteActionCommand,
    RecoverUnknownDeleteActionService,
    RecoverUnknownSendActionCommand,
    RecoverUnknownSendActionService,
    RecoverUnknownUpdateActionCommand,
    RecoverUnknownUpdateActionService,
    ResultCode,
    _approve_effect_action,
    _begin_claimed_action,
    _claim_effect_action,
    _insert_calendar_event_reference,
    _insert_task_delete_reference,
    _mark_effect_unknown,
    _prepare_claimed_action,
    _prepare_effect_write_plan,
    _prepare_update_claimed_action,
    _TransactionCheckingGateway,
    cast,
    classify_write_delivery,
    connect_sqlite,
    pytest,
    sqlite_unit_of_work_factory,
)
from tests.support.fakes import DeterministicUUID

pytest_plugins = ("tests.integration.persistence.test_write_actions",)


def test_unknown_task_delete_recovers_from_target_absence_without_redelete(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    _insert_task_delete_reference(write_database)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete",
        tool_name="tasks_delete_task",
        arguments={"task_list_id": "task-list-default", "task_id": "task-followup"},
        expected={"resource_type": "task", "resource_id": "task-followup", "absent": True},
        target_resource_ref_id="resource-task-followup",
    )
    approved = _approve_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete",
    )
    claimed = _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete",
        expected_version=approved.action_version,
    )
    fixture_gateway.queue_fault(
        operation="delete_task",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.TIMEOUT_AFTER_DELIVERY),
    )
    execute_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )

    with pytest.raises(GoogleWorkspaceGatewayError) as error_info:
        execute_service(
            action_id="action-recover-task-delete",
            claim_token=claimed.claim_token or "",
        )
    _mark_effect_unknown(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete",
        error=error_info.value,
    )

    recovered = RecoverUnknownDeleteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        RecoverUnknownDeleteActionCommand(
            command_id="recover-task-delete-1",
            request_hash="f2" * 32,
            action_id="action-recover-task-delete",
            attempt_id="attempt-recover-task-delete",
            expected_action_version=3,
            expected_attempt_version=2,
        )
    )

    assert recovered.action_status == "EXECUTED"
    assert fixture_gateway.count_calls("delete_task") == 1


def test_unknown_task_delete_with_present_target_requires_reapproval_not_redelete(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    _insert_task_delete_reference(write_database)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete-present",
        tool_name="tasks_delete_task",
        arguments={"task_list_id": "task-list-default", "task_id": "task-followup"},
        expected={"resource_type": "task", "resource_id": "task-followup", "absent": True},
        target_resource_ref_id="resource-task-followup",
    )
    approved = _approve_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete-present",
    )
    claimed = _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete-present",
        expected_version=approved.action_version,
    )
    _begin_claimed_action(
        write_database=write_database,
        clock=clock,
        claimed=claimed,
    )
    _mark_effect_unknown(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete-present",
        error=GoogleWorkspaceGatewayError(
            code=GoogleWorkspaceErrorCode.TIMEOUT,
            message="delivery uncertain",
            delivered=True,
            mutated=False,
        ),
    )

    recovered = RecoverUnknownDeleteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        RecoverUnknownDeleteActionCommand(
            command_id="recover-task-delete-present-1",
            request_hash="f3" * 32,
            action_id="action-recover-task-delete-present",
            attempt_id="attempt-recover-task-delete-present",
            expected_action_version=3,
            expected_attempt_version=2,
        )
    )

    assert recovered.result_code == ResultCode.RECOVERY_REQUIRED.value
    assert fixture_gateway.count_calls("delete_task") == 0


def test_unknown_gmail_send_recovers_by_fingerprint_without_resending(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="recover-send",
        tool_name="gmail_send",
        arguments={"draft_id": "draft-followup"},
        expected={},
    )
    approved = _approve_effect_action(
        write_database=write_database, clock=clock, suffix="recover-send"
    )
    claimed = _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-send",
        expected_version=approved.action_version,
    )
    fixture_gateway.queue_fault(
        operation="send_gmail",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.HTTP_500),
    )
    execute_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )

    with pytest.raises(GoogleWorkspaceGatewayError) as error_info:
        execute_service(
            action_id="action-recover-send",
            claim_token=claimed.claim_token or "",
        )
    assert classify_write_delivery(error_info.value) is DeliveryCertainty.SENT_RESPONSE_LOST
    _mark_effect_unknown(
        write_database=write_database,
        clock=clock,
        suffix="recover-send",
        error=error_info.value,
    )

    recovered = RecoverUnknownSendActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        RecoverUnknownSendActionCommand(
            command_id="recover-send-1",
            request_hash="e0" * 32,
            action_id="action-recover-send",
            attempt_id="attempt-recover-send",
            expected_action_version=3,
            expected_attempt_version=2,
        )
    )

    assert recovered.action_status == "EXECUTED"
    assert fixture_gateway.count_calls("send_gmail") == 1
    assert fixture_gateway.count_calls("search_by_recovery_fingerprint") == 1


def test_unknown_calendar_delete_recovers_from_target_absence_without_redelete(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    _insert_calendar_event_reference(write_database)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete",
        tool_name="calendar_delete_event",
        arguments={"calendar_id": "calendar-primary", "event_id": "event-focus"},
        expected={"resource_type": "calendar_event", "resource_id": "event-focus", "absent": True},
        target_resource_ref_id="resource-event-focus",
    )
    approved = _approve_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete",
    )
    claimed = _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete",
        expected_version=approved.action_version,
    )
    fixture_gateway.queue_fault(
        operation="delete_calendar_event",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.TIMEOUT_AFTER_DELIVERY),
    )
    execute_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )

    with pytest.raises(GoogleWorkspaceGatewayError) as error_info:
        execute_service(
            action_id="action-recover-delete",
            claim_token=claimed.claim_token or "",
        )
    _mark_effect_unknown(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete",
        error=error_info.value,
    )

    recovered = RecoverUnknownDeleteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        RecoverUnknownDeleteActionCommand(
            command_id="recover-delete-1",
            request_hash="f0" * 32,
            action_id="action-recover-delete",
            attempt_id="attempt-recover-delete",
            expected_action_version=3,
            expected_attempt_version=2,
        )
    )

    assert recovered.action_status == "EXECUTED"
    assert fixture_gateway.count_calls("delete_calendar_event") == 1


def test_unknown_calendar_delete_with_present_target_requires_reapproval_not_redelete(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    _insert_calendar_event_reference(write_database)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete-present",
        tool_name="calendar_delete_event",
        arguments={"calendar_id": "calendar-primary", "event_id": "event-focus"},
        expected={"resource_type": "calendar_event", "resource_id": "event-focus", "absent": True},
        target_resource_ref_id="resource-event-focus",
    )
    approved = _approve_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete-present",
    )
    claimed = _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete-present",
        expected_version=approved.action_version,
    )
    _begin_claimed_action(
        write_database=write_database,
        clock=clock,
        claimed=claimed,
    )
    _mark_effect_unknown(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete-present",
        error=GoogleWorkspaceGatewayError(
            code=GoogleWorkspaceErrorCode.TIMEOUT,
            message="delivery uncertain",
            delivered=True,
            mutated=False,
        ),
    )

    recovered = RecoverUnknownDeleteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        RecoverUnknownDeleteActionCommand(
            command_id="recover-delete-present-1",
            request_hash="f1" * 32,
            action_id="action-recover-delete-present",
            attempt_id="attempt-recover-delete-present",
            expected_action_version=3,
            expected_attempt_version=2,
        )
    )

    assert recovered.result_code == ResultCode.RECOVERY_REQUIRED.value
    assert fixture_gateway.count_calls("delete_calendar_event") == 0


def test_unknown_result_create_recovery_and_retry_flow(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    claimed = _prepare_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-create",
    )
    execute_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    fixture_gateway.queue_fault(
        operation="create_task",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.TIMEOUT_AFTER_DELIVERY),
    )

    with pytest.raises(GoogleWorkspaceGatewayError) as error_info:
        execute_service(
            action_id="action-recover-create",
            claim_token=claimed.claim_token or "",
        )
    assert classify_write_delivery(error_info.value) is DeliveryCertainty.SENT_RESPONSE_LOST

    unknown_service = MarkWriteActionUnknownResultService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    unknown = unknown_service(
        MarkWriteActionUnknownResultCommand(
            command_id="unknown-create-1",
            request_hash="u1" * 32,
            action_id="action-recover-create",
            attempt_id="attempt-recover-create",
            expected_action_version=2,
            expected_attempt_version=1,
            error_code=error_info.value.code.value,
            error_detail=str(error_info.value),
        )
    )
    assert unknown.applied is True
    assert unknown.action_status == "UNKNOWN_RESULT"

    recover_service = RecoverUnknownCreateActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )
    recovered = recover_service(
        RecoverUnknownCreateActionCommand(
            command_id="recover-create-1",
            request_hash="u2" * 32,
            action_id="action-recover-create",
            attempt_id="attempt-recover-create",
            expected_action_version=3,
            expected_attempt_version=2,
        )
    )
    assert recovered.applied is True
    assert recovered.action_status == "EXECUTED"
    resumed = ResolveRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        ResolveRecoveryCommandV1(
            run_id="run-1",
            expected_version=2,
            command_id="recheck-recover-create",
            request_hash="u3" * 32,
            resolution=RecoveryResolution.RECHECK,
        )
    )
    assert resumed.current_status == "VERIFYING"

    connection = connect_sqlite(write_database)
    try:
        rows = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1') AS run_status,
                (SELECT status FROM actions WHERE id = 'action-recover-create') AS action_status,
                (
                    SELECT status
                    FROM execution_attempts
                    WHERE id = 'attempt-recover-create'
                ) AS attempt_status;
            """
        ).fetchone()
        assert tuple(rows) == ("VERIFYING", "EXECUTED", "SUCCEEDED")
    finally:
        connection.close()


def test_unknown_result_mcp_request_id_persists_on_trace_and_audit(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    """E: an execution-phase TIMEOUT/other error's mcp_request_id (as
    execution_phase.py forwards it from a real GoogleWorkspaceGatewayError)
    reaches the persisted WRITE_ACTION_UNKNOWN_RESULT trace and
    WRITE_UNKNOWN_RESULT audit rows.
    """
    clock = FakeClockPort(1000)
    claimed = _prepare_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-unknown-mcp",
    )
    execute_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    fixture_gateway.queue_fault(
        operation="create_task",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.TIMEOUT_AFTER_DELIVERY),
    )
    with pytest.raises(GoogleWorkspaceGatewayError) as error_info:
        execute_service(
            action_id="action-recover-unknown-mcp",
            claim_token=claimed.claim_token or "",
        )

    unknown_service = MarkWriteActionUnknownResultService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    unknown = unknown_service(
        MarkWriteActionUnknownResultCommand(
            command_id="unknown-mcp-1",
            request_hash="u9" * 32,
            action_id="action-recover-unknown-mcp",
            attempt_id="attempt-recover-unknown-mcp",
            expected_action_version=2,
            expected_attempt_version=1,
            error_code=error_info.value.code.value,
            error_detail=str(error_info.value),
            mcp_request_id="req-simulated-77",
        )
    )
    assert unknown.applied is True

    connection = connect_sqlite(write_database)
    try:
        trace_row = connection.execute(
            "SELECT payload_json FROM trace_events "
            "WHERE event_type = 'WRITE_ACTION_UNKNOWN_RESULT' "
            "AND action_id = 'action-recover-unknown-mcp';"
        ).fetchone()
        audit_row = connection.execute(
            "SELECT metadata_json FROM audit_events "
            "WHERE event_type = 'WRITE_UNKNOWN_RESULT' "
            "AND action_id = 'action-recover-unknown-mcp';"
        ).fetchone()
    finally:
        connection.close()

    trace_envelope = _loads(trace_row[0])
    audit_envelope = _loads(audit_row[0])
    assert trace_envelope["attributes"]["mcp_request_id"] == "req-simulated-77"
    assert audit_envelope["attributes"]["mcp_request_id"] == "req-simulated-77"


def test_update_recovery_can_resolve_unknown_as_failed_when_source_is_unchanged(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    _prepare_update_claimed_action(write_database=write_database, clock=clock, suffix="update")

    unknown_service = MarkWriteActionUnknownResultService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    unknown_service(
        MarkWriteActionUnknownResultCommand(
            command_id="unknown-update-1",
            request_hash="v1" * 32,
            action_id="action-update",
            attempt_id="attempt-update",
            expected_action_version=2,
            expected_attempt_version=1,
            error_code=GoogleWorkspaceErrorCode.TIMEOUT.value,
            error_detail="timeout after delivery",
        )
    )

    recover_service = RecoverUnknownUpdateActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )
    resolved = recover_service(
        RecoverUnknownUpdateActionCommand(
            command_id="recover-update-1",
            request_hash="v2" * 32,
            action_id="action-update",
            attempt_id="attempt-update",
            expected_action_version=3,
            expected_attempt_version=2,
        )
    )
    assert resolved.applied is True
    assert resolved.action_status == "FAILED"

    _seed_workflow_checkpoint(write_database, clock)
    scheduled: list[str] = []
    retry_service = PrepareWriteRetryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        id_generator=DeterministicUUID(prefix="retry-review"),
        resume_target_registry=ResumeTargetRegistry(
            node_registry=NodeRegistry(graph_version=RESUME_CONTRACT_VERSION),
            graph_version=RESUME_CONTRACT_VERSION,
        ),
        schedule_run_execution=lambda command: scheduled.append(command.handoff_id),  # type: ignore[arg-type,return-value]
    )
    retry_command = PrepareWriteRetryCommand(
        command_id="retry-update-1",
        request_hash="v3" * 32,
        action_id="action-update",
        expected_action_version=4,
    )
    retried = retry_service(retry_command)
    replayed = retry_service(retry_command)
    assert retried.applied is True
    assert retried.action_status == "MODIFIED"
    assert retried.handoff_id is not None
    assert scheduled == [retried.handoff_id]
    assert replayed.request_replayed is True
    assert replayed.handoff_id == retried.handoff_id
    with connect_sqlite(write_database) as connection:
        handoff = connection.execute(
            "SELECT status, resume_target_json FROM workflow_handoffs WHERE handoff_id=?;",
            (retried.handoff_id,),
        ).fetchone()
        handoff_count = connection.execute(
            "SELECT COUNT(*) FROM workflow_handoffs WHERE trigger_command_id=?;",
            (retry_command.command_id,),
        ).fetchone()[0]
        audit_count = connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type='WRITE_RETRY_PREPARED' "
            "AND action_id='action-update';"
        ).fetchone()[0]
    assert handoff is not None and handoff["status"] == "PENDING"
    assert _loads(handoff["resume_target_json"])["stage_id"] == "REVIEW_ENTRY"
    assert handoff_count == 1
    assert audit_count == 1


def test_update_recovery_get_runs_without_sqlite_write_transaction(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    _prepare_update_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix="boundary-update",
    )
    unknown_service = MarkWriteActionUnknownResultService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    unknown_service(
        MarkWriteActionUnknownResultCommand(
            command_id="unknown-boundary-update",
            request_hash="l1" * 32,
            action_id="action-boundary-update",
            attempt_id="attempt-boundary-update",
            expected_action_version=2,
            expected_attempt_version=1,
            error_code=GoogleWorkspaceErrorCode.TIMEOUT.value,
            error_detail="timeout after delivery",
        )
    )
    recover_service = RecoverUnknownUpdateActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=cast(
            GoogleWorkspaceGateway,
            _TransactionCheckingGateway(
                delegate=fixture_gateway,
                database_path=write_database,
            ),
        ),
    )

    resolved = recover_service(
        RecoverUnknownUpdateActionCommand(
            command_id="recover-boundary-update",
            request_hash="l2" * 32,
            action_id="action-boundary-update",
            attempt_id="attempt-boundary-update",
            expected_action_version=3,
            expected_attempt_version=2,
        )
    )

    assert resolved.applied is True
    assert resolved.action_status == "FAILED"
