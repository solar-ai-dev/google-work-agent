"""UNKNOWN_RESULT and recovery integration tests."""

# ruff: noqa: F401

from __future__ import annotations

from tests.integration.persistence.test_write_actions import (
    DeliveryCertainty,
    ExecuteWriteActionService,
    FakeClock,
    FakeGoogleGateway,
    GoogleGatewayFault,
    GoogleGatewayFaultKind,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceExecutionBackend,
    GoogleWorkspaceGateway,
    GoogleWorkspaceGatewayError,
    MarkWriteActionUnknownResultCommand,
    MarkWriteActionUnknownResultService,
    Path,
    PrepareWriteRetryCommand,
    PrepareWriteRetryService,
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

pytest_plugins = ("tests.integration.persistence.test_write_actions",)


def test_unknown_task_delete_recovers_from_target_absence_without_redelete(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
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
            expected_attempt_version=1,
        )
    )

    assert recovered.action_status == "EXECUTED"
    assert fixture_gateway.count_calls("delete_task") == 1


def test_unknown_task_delete_with_present_target_requires_reapproval_not_redelete(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
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
    _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete-present",
        expected_version=approved.action_version,
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
            expected_attempt_version=1,
        )
    )

    assert recovered.result_code == ResultCode.RECOVERY_REQUIRED.value
    assert fixture_gateway.count_calls("delete_task") == 0


def test_unknown_gmail_send_recovers_by_fingerprint_without_resending(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
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
            expected_attempt_version=1,
        )
    )

    assert recovered.action_status == "EXECUTED"
    assert fixture_gateway.count_calls("send_gmail") == 1
    assert fixture_gateway.count_calls("search_by_recovery_fingerprint") == 1


def test_unknown_calendar_delete_recovers_from_target_absence_without_redelete(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
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
            expected_attempt_version=1,
        )
    )

    assert recovered.action_status == "EXECUTED"
    assert fixture_gateway.count_calls("delete_calendar_event") == 1


def test_unknown_calendar_delete_with_present_target_requires_reapproval_not_redelete(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
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
    _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete-present",
        expected_version=approved.action_version,
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
            expected_attempt_version=1,
        )
    )

    assert recovered.result_code == ResultCode.RECOVERY_REQUIRED.value
    assert fixture_gateway.count_calls("delete_calendar_event") == 0


def test_unknown_result_create_recovery_and_retry_flow(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
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
            expected_attempt_version=0,
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
            expected_attempt_version=1,
        )
    )
    assert recovered.applied is True
    assert recovered.action_status == "EXECUTED"

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


def test_update_recovery_can_resolve_unknown_as_failed_when_source_is_unchanged(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
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
            expected_attempt_version=0,
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
            expected_attempt_version=1,
        )
    )
    assert resolved.applied is True
    assert resolved.action_status == "FAILED"

    retry_service = PrepareWriteRetryService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    retried = retry_service(
        PrepareWriteRetryCommand(
            command_id="retry-update-1",
            request_hash="v3" * 32,
            action_id="action-update",
            expected_action_version=4,
        )
    )
    assert retried.applied is True
    assert retried.action_status == "MODIFIED"


def test_update_recovery_get_runs_without_sqlite_write_transaction(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
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
            expected_attempt_version=0,
            error_code=GoogleWorkspaceErrorCode.TIMEOUT.value,
            error_detail="timeout after delivery",
        )
    )
    recover_service = RecoverUnknownUpdateActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=GoogleWorkspaceExecutionBackend(
            gateway=cast(
                GoogleWorkspaceGateway,
                _TransactionCheckingGateway(
                    delegate=fixture_gateway,
                    database_path=write_database,
                ),
            )
        ),
    )

    resolved = recover_service(
        RecoverUnknownUpdateActionCommand(
            command_id="recover-boundary-update",
            request_hash="l2" * 32,
            action_id="action-boundary-update",
            attempt_id="attempt-boundary-update",
            expected_action_version=3,
            expected_attempt_version=1,
        )
    )

    assert resolved.applied is True
    assert resolved.action_status == "FAILED"
