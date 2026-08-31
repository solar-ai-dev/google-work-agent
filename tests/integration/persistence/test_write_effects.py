"""Provider effect and preflight integration tests."""

from __future__ import annotations

from tests.integration.persistence.test_write_actions import (
    DeliveryCertainty,
    ExecuteWriteActionService,
    FakeClockPort,
    FakeGoogleGateway,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    Path,
    PolicyViolationError,
    StoreWriteActionSuccessCommand,
    StoreWriteActionSuccessService,
    VerifyWriteActionCommand,
    VerifyWriteActionService,
    _approve_effect_action,
    _claim_effect_action,
    _insert_calendar_event_reference,
    _insert_task_delete_reference,
    _prepare_effect_write_plan,
    build_claim_preflight,
    classify_write_delivery,
    is_reauth_required_error,
    pytest,
    sqlite_unit_of_work_factory,
)

pytest_plugins = ("tests.integration.persistence.test_write_actions",)


def test_delivery_certainty_and_reauth_classification_are_pure() -> None:
    not_sent = GoogleWorkspaceGatewayError(
        code=GoogleWorkspaceErrorCode.TIMEOUT,
        message="timeout before delivery",
        delivered=False,
        mutated=False,
    )
    uncertain = GoogleWorkspaceGatewayError(
        code=GoogleWorkspaceErrorCode.TIMEOUT,
        message="timeout after delivery",
        delivered=True,
        mutated=False,
    )
    response_lost = GoogleWorkspaceGatewayError(
        code=GoogleWorkspaceErrorCode.AUTH_EXPIRED,
        message="auth expired after mutation",
        delivered=True,
        mutated=True,
    )

    assert classify_write_delivery(not_sent) is DeliveryCertainty.NOT_SENT
    assert classify_write_delivery(uncertain) is DeliveryCertainty.MAY_HAVE_BEEN_SENT
    assert classify_write_delivery(response_lost) is DeliveryCertainty.SENT_RESPONSE_LOST
    assert is_reauth_required_error(not_sent) is False
    assert is_reauth_required_error(response_lost) is True


def test_gmail_send_uses_approval_claim_sent_lookup_and_verification(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="send",
        tool_name="gmail_send",
        arguments={"draft_id": "draft-followup"},
        expected={
            "resource_type": "gmail_message",
            "resource_id": "sent-draft-followup",
            "parent_id": "thread-project",
            "version": "1",
            "payload": {
                "thread_id": "thread-project",
                "to": ["pm@example.com"],
                "subject": "Re: Project sync follow-up",
                "body": "Draft summary is ready for review.",
                "draft_id": "draft-followup",
                "sent": True,
                "resource_id": "sent-draft-followup",
            },
        },
    )
    approved = _approve_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="send",
    )
    build_claim_preflight(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
    )(action_id="action-send")
    claimed = _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="send",
        expected_version=approved.action_version,
    )
    executed = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )(action_id="action-send", claim_token=claimed.claim_token or "")
    stored = StoreWriteActionSuccessService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        StoreWriteActionSuccessCommand(
            command_id="store-send",
            request_hash="s1" * 32,
            action_id="action-send",
            attempt_id="attempt-send",
            expected_action_version=claimed.action_version,
            expected_attempt_version=1,
            snapshot=executed.snapshot,
        )
    )
    verified = VerifyWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        VerifyWriteActionCommand(
            command_id="verify-send",
            request_hash="s2" * 32,
            action_id="action-send",
            attempt_id="attempt-send",
            expected_action_version=stored.action_version,
            verification_id="verification-send",
        )
    )

    assert verified.action_status == "VERIFIED"
    assert fixture_gateway.count_calls("send_gmail") == 1
    assert fixture_gateway.count_calls("get_gmail_message") == 1


def test_calendar_delete_uses_preflight_claim_get_absent_and_verification(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    _insert_calendar_event_reference(write_database)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="delete",
        tool_name="calendar_delete_event",
        arguments={"calendar_id": "calendar-primary", "event_id": "event-focus"},
        expected={"resource_type": "calendar_event", "resource_id": "event-focus", "absent": True},
        target_resource_ref_id="resource-event-focus",
    )
    approved = _approve_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="delete",
    )
    build_claim_preflight(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
    )(action_id="action-delete")
    claimed = _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="delete",
        expected_version=approved.action_version,
    )
    executed = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )(action_id="action-delete", claim_token=claimed.claim_token or "")
    stored = StoreWriteActionSuccessService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        StoreWriteActionSuccessCommand(
            command_id="store-delete",
            request_hash="d1" * 32,
            action_id="action-delete",
            attempt_id="attempt-delete",
            expected_action_version=claimed.action_version,
            expected_attempt_version=1,
            snapshot=executed.snapshot,
        )
    )
    verified = VerifyWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        VerifyWriteActionCommand(
            command_id="verify-delete",
            request_hash="d2" * 32,
            action_id="action-delete",
            attempt_id="attempt-delete",
            expected_action_version=stored.action_version,
            verification_id="verification-delete",
        )
    )

    assert verified.action_status == "VERIFIED"
    assert fixture_gateway.count_calls("delete_calendar_event") == 1
    assert fixture_gateway.count_calls("get_calendar_event") == 1


def test_calendar_delete_preflight_rejects_recurring_series_scope(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    _insert_calendar_event_reference(write_database)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="delete-series",
        tool_name="calendar_delete_event",
        arguments={
            "calendar_id": "calendar-primary",
            "event_id": "event-focus",
            "delete_scope": "SERIES",
        },
        expected={"resource_type": "calendar_event", "resource_id": "event-focus", "absent": True},
        target_resource_ref_id="resource-event-focus",
    )
    _approve_effect_action(write_database=write_database, clock=clock, suffix="delete-series")

    with pytest.raises(PolicyViolationError, match="recurring series deletion"):
        build_claim_preflight(
            unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
            gateway=fixture_gateway,
        )(action_id="action-delete-series")

    assert fixture_gateway.count_calls("delete_calendar_event") == 0


def test_calendar_delete_preflight_rejects_target_version_change(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    _insert_calendar_event_reference(write_database, version="6")
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="delete-stale",
        tool_name="calendar_delete_event",
        arguments={"calendar_id": "calendar-primary", "event_id": "event-focus"},
        expected={"resource_type": "calendar_event", "resource_id": "event-focus", "absent": True},
        target_resource_ref_id="resource-event-focus",
    )
    _approve_effect_action(write_database=write_database, clock=clock, suffix="delete-stale")

    with pytest.raises(PolicyViolationError, match="target version mismatch"):
        build_claim_preflight(
            unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
            gateway=fixture_gateway,
        )(action_id="action-delete-stale")

    assert fixture_gateway.count_calls("delete_calendar_event") == 0


def test_task_delete_uses_preflight_claim_get_absent_and_verification(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    _insert_task_delete_reference(write_database)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="task-delete",
        tool_name="tasks_delete_task",
        arguments={"task_list_id": "task-list-default", "task_id": "task-followup"},
        expected={"resource_type": "task", "resource_id": "task-followup", "absent": True},
        target_resource_ref_id="resource-task-followup",
    )
    approved = _approve_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="task-delete",
    )
    build_claim_preflight(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
    )(action_id="action-task-delete")
    claimed = _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="task-delete",
        expected_version=approved.action_version,
    )
    executed = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )(action_id="action-task-delete", claim_token=claimed.claim_token or "")
    stored = StoreWriteActionSuccessService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        StoreWriteActionSuccessCommand(
            command_id="store-task-delete",
            request_hash="d3" * 32,
            action_id="action-task-delete",
            attempt_id="attempt-task-delete",
            expected_action_version=claimed.action_version,
            expected_attempt_version=1,
            snapshot=executed.snapshot,
        )
    )
    verified = VerifyWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        VerifyWriteActionCommand(
            command_id="verify-task-delete",
            request_hash="d4" * 32,
            action_id="action-task-delete",
            attempt_id="attempt-task-delete",
            expected_action_version=stored.action_version,
            verification_id="verification-task-delete",
        )
    )

    assert verified.action_status == "VERIFIED"
    assert fixture_gateway.count_calls("delete_task") == 1
    assert fixture_gateway.count_calls("get_task") == 1


def test_task_delete_plan_requires_confirmation_when_evidence_is_not_independent(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    with pytest.raises(
        PolicyViolationError, match="EXISTING_RESOURCE_AUTHORITY_CONFIRMATION_REQUIRED"
    ):
        _prepare_effect_write_plan(
            write_database=write_database,
            clock=clock,
            suffix="task-delete-ambiguous",
            tool_name="tasks_delete_task",
            arguments={"task_list_id": "task-list-default", "task_id": "task-followup"},
            expected={
                "resource_type": "task",
                "resource_id": "task-followup",
                "absent": True,
            },
            target_resource_ref_id=None,
            evidence_count=2,
        )

    assert fixture_gateway.count_calls("delete_task") == 0


def test_task_delete_preflight_rejects_target_version_change(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    _insert_task_delete_reference(write_database, version="99")
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="task-delete-stale",
        tool_name="tasks_delete_task",
        arguments={"task_list_id": "task-list-default", "task_id": "task-followup"},
        expected={"resource_type": "task", "resource_id": "task-followup", "absent": True},
        target_resource_ref_id="resource-task-followup",
    )
    _approve_effect_action(write_database=write_database, clock=clock, suffix="task-delete-stale")

    with pytest.raises(PolicyViolationError, match="target version mismatch"):
        build_claim_preflight(
            unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
            gateway=fixture_gateway,
        )(action_id="action-task-delete-stale")

    assert fixture_gateway.count_calls("delete_task") == 0
