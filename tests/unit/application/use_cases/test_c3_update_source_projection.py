from __future__ import annotations

from json import dumps
from types import SimpleNamespace

import pytest
from tests.support.legacy_write.recover_update import (
    RecoverUpdateCommand,
    RecoverUpdateHandler,
)

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.ports.connector.contracts.google_workspace import (
    ResourceSnapshot,
    ResourceType,
)


class _ByIdRepo:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def get_by_id(self, value_id: str) -> object | None:
        return self.values.get(value_id)

    def get(self, value_id: str) -> object | None:
        return self.values.get(value_id)


class _Uow:
    def __init__(self, *, action: object, attempt: object, approval: object) -> None:
        self.actions = _ByIdRepo({action.id: action})
        self.execution_attempts = _ByIdRepo({attempt.id: attempt})
        self.approvals = _ByIdRepo({approval.id: approval})
        self.approvals = self.approvals
        self.resource_refs = _ByIdRepo({})

    def __enter__(self) -> _Uow:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _Connector:
    def __init__(self, snapshot: ResourceSnapshot) -> None:
        self.snapshot = snapshot
        self.read_calls = 0
        self.write_calls = 0

    def fetch_verification_snapshot(self, **_kwargs: object) -> ResourceSnapshot:
        self.read_calls += 1
        return self.snapshot

    def execute_write(self, _request: object) -> ResourceSnapshot:
        self.write_calls += 1
        raise AssertionError("UPDATE recovery must never dispatch a write")


def _result(status: str) -> SimpleNamespace:
    return SimpleNamespace(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED.value,
        action_id="action-1",
        action_status=status,
        action_version=4,
        next_allowed_commands=(),
        attempt_id="attempt-1",
        safe_error_code=None,
        conflict_detail=None,
    )


def _run_update(
    *,
    tool_name: str,
    arguments: dict[str, object],
    expected: dict[str, object],
    source: dict[str, object],
    actual: ResourceSnapshot,
) -> tuple[object, list[object], list[object], _Connector]:
    action = SimpleNamespace(
        id="action-1",
        plan_id="plan-1",
        tool_name=tool_name,
        arguments_json=dumps(arguments),
        expected_json=dumps(expected),
        target_resource_ref_id=None,
        status=ActionStatusV1.UNKNOWN_RESULT.value,
        version=3,
    )
    attempt = SimpleNamespace(
        id="attempt-1",
        approval_id="approval-1",
        status=ExecutionAttemptStatusV1.UNKNOWN_RESULT,
    )
    approval = SimpleNamespace(
        id="approval-1",
        action_id="action-1",
        source_snapshot_json=dumps(source),
    )
    uow = _Uow(action=action, attempt=attempt, approval=approval)
    connector = _Connector(actual)
    recovered: list[object] = []
    failed: list[object] = []
    result = RecoverUpdateHandler(
        unit_of_work_factory=lambda: uow,  # type: ignore[arg-type]
        connector_execution=connector,  # type: ignore[arg-type]
        recover_existing_result=(
            lambda command: recovered.append(command) or _result(ActionStatusV1.EXECUTED.value)
        ),
        resolve_as_failed=(
            lambda command: failed.append(command) or _result(ActionStatusV1.FAILED.value)
        ),
    )(
        RecoverUpdateCommand(
            "recover-update",
            "hash",
            "action-1",
            "attempt-1",
            3,
            1,
        )
    )
    return result, recovered, failed, connector


def _task_snapshot(
    *, title: str, version: str, extra: dict[str, object] | None = None
) -> ResourceSnapshot:
    return ResourceSnapshot(
        fixture_snapshot_id="task-fixture",
        resource_type=ResourceType.TASK,
        resource_id="task-1",
        parent_id="list-1",
        related_resource_ids=("list-1",),
        version=version,
        recovery_fingerprint=None,
        payload={"title": title, **(extra or {})},
    )


def _calendar_snapshot(
    *, title: str, version: str, extra: dict[str, object] | None = None
) -> ResourceSnapshot:
    return ResourceSnapshot(
        fixture_snapshot_id="calendar-fixture",
        resource_type=ResourceType.CALENDAR_EVENT,
        resource_id="event-1",
        parent_id="calendar-1",
        related_resource_ids=("calendar-1",),
        version=version,
        recovery_fingerprint=None,
        payload={
            "title": title,
            "start": "2026-08-22T09:00:00+09:00",
            "end": "2026-08-22T10:00:00+09:00",
            **(extra or {}),
        },
    )


def test_tasks_update_unchanged_source_with_provider_extras_resolves_failed() -> None:
    result, recovered, failed, connector = _run_update(
        tool_name="tasks_update_task",
        arguments={
            "task_list_id": "list-1",
            "task_id": "task-1",
            "payload": {"title": "after"},
        },
        expected={"payload": {"title": "after"}},
        source={
            "resource_type": ResourceType.TASK.value,
            "resource_id": "task-1",
            "parent_id": "list-1",
            "version": "1",
            "payload": {"title": "before"},
        },
        actual=_task_snapshot(title="before", version="1", extra={"notes": "provider-extra"}),
    )
    assert result.action_status == ActionStatusV1.FAILED.value
    assert recovered == [] and len(failed) == 1
    assert connector.read_calls == 1 and connector.write_calls == 0


@pytest.mark.parametrize(
    "metadata",
    [
        {"calendar_conflict": {"risk": {"decision": "WARNING"}, "acknowledged": True}},
        {"feasibility": {"decision": "FEASIBLE", "reason_codes": []}},
        {
            "calendar_conflict": {
                "risk": {"decision": "HARD_CONFLICT"},
                "acknowledged": True,
            },
            "feasibility": {"decision": "FEASIBLE", "reason_codes": []},
        },
    ],
)
def test_calendar_update_policy_metadata_does_not_pollute_source_comparison(
    metadata: dict[str, object],
) -> None:
    source = {
        "resource_type": ResourceType.CALENDAR_EVENT.value,
        "resource_id": "event-1",
        "parent_id": "calendar-1",
        "version": "7",
        "payload": {
            "title": "before",
            "start": "2026-08-22T09:00:00+09:00",
            "end": "2026-08-22T10:00:00+09:00",
        },
        **metadata,
    }
    result, recovered, failed, connector = _run_update(
        tool_name="calendar_update_event",
        arguments={
            "calendar_id": "calendar-1",
            "event_id": "event-1",
            "payload": {"title": "after"},
        },
        expected={"payload": {"title": "after"}},
        source=source,
        actual=_calendar_snapshot(
            title="before",
            version="7",
            extra={"provider_generated": "irrelevant"},
        ),
    )
    assert result.action_status == ActionStatusV1.FAILED.value
    assert recovered == [] and len(failed) == 1
    assert connector.read_calls == 1 and connector.write_calls == 0


def test_update_expected_state_with_provider_extras_recovers_existing_result() -> None:
    result, recovered, failed, connector = _run_update(
        tool_name="tasks_update_task",
        arguments={
            "task_list_id": "list-1",
            "task_id": "task-1",
            "payload": {"title": "after"},
        },
        expected={"payload": {"title": "after"}},
        source={"resource_id": "task-1", "version": "1"},
        actual=_task_snapshot(title="after", version="2", extra={"notes": "provider-extra"}),
    )
    assert result.action_status == ActionStatusV1.EXECUTED.value
    assert len(recovered) == 1 and failed == []
    assert connector.read_calls == 1 and connector.write_calls == 0


def test_update_third_state_remains_recovery_required() -> None:
    result, recovered, failed, connector = _run_update(
        tool_name="tasks_update_task",
        arguments={
            "task_list_id": "list-1",
            "task_id": "task-1",
            "payload": {"title": "after"},
        },
        expected={"payload": {"title": "after"}},
        source={"resource_id": "task-1", "version": "1", "payload": {"title": "before"}},
        actual=_task_snapshot(title="someone-else", version="3"),
    )
    assert result.applied is False
    assert result.result_code == ResultCode.RECOVERY_REQUIRED.value
    assert recovered == [] and failed == []
    assert connector.read_calls == 1 and connector.write_calls == 0


def test_policy_only_source_snapshot_cannot_vacuously_confirm_not_sent() -> None:
    result, recovered, failed, _connector = _run_update(
        tool_name="calendar_update_event",
        arguments={
            "calendar_id": "calendar-1",
            "event_id": "event-1",
            "payload": {"title": "after"},
        },
        expected={"payload": {"title": "after"}},
        source={
            "calendar_conflict": {"risk": {"decision": "WARNING"}, "acknowledged": True},
            "feasibility": {"decision": "FEASIBLE"},
        },
        actual=_calendar_snapshot(title="before", version="7"),
    )
    assert result.applied is False
    assert result.result_code == ResultCode.RECOVERY_REQUIRED.value
    assert recovered == [] and failed == []
