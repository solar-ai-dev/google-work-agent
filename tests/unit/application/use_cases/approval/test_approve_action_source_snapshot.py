from __future__ import annotations

from dataclasses import replace
from json import loads

import pytest

from google_work_agent.application.use_cases.approval.approve_action import (
    ApproveActionCommand,
    ApproveActionHandler,
)
from google_work_agent.application.approval_source_snapshot import (
    merge_approval_snapshot_metadata,
)
from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    CommandResult,
    EffectType,
    PolicyViolationError,
    ResultCode,
    next_allowed_action_commands,
)
from google_work_agent.ports import (
    ActionRecord,
    PlanRecord,
    PlanReviewStatus,
    PlanStatus,
    ResourceRefRecord,
    ResourceSource,
    StoredResourceType,
)


class _Sink:
    def __init__(self) -> None:
        self.items: list[object] = []

    def add(self, item: object) -> None:
        self.items.append(item)


class _ActionRepository:
    def __init__(self, action: ActionRecord) -> None:
        self.action = action

    def get_by_id(self, action_id: str) -> ActionRecord | None:
        return self.action if self.action.id == action_id else None

    def approve_write(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        action = self.get_by_id(action_id)
        assert action is not None
        assert action.version == expected_version
        new_version = action.version + 1
        self.action = replace(
            action,
            status=ActionStatus.APPROVED.value,
            version=new_version,
            updated_at_ms=updated_at_ms,
        )
        return CommandResult(
            applied=True,
            result_code=ResultCode.TRANSITION_APPLIED,
            current_status=ActionStatus.APPROVED,
            current_version=new_version,
            next_allowed_commands=next_allowed_action_commands(
                ActionStatus.APPROVED,
                effect_type=EffectType(action.effect_type),
            ),
        )


class _PlanRepository:
    def __init__(self, plan: PlanRecord) -> None:
        self.plan = plan

    def get_by_id(self, plan_id: str) -> PlanRecord | None:
        return self.plan if self.plan.id == plan_id else None

    def activate_waiting(self, plan_id: str) -> None:
        assert self.plan.id == plan_id
        self.plan = replace(self.plan, status=PlanStatus.ACTIVE)


class _ResourceRefRepository:
    def __init__(self, resource_ref: ResourceRefRecord | None) -> None:
        self.resource_ref = resource_ref

    def get(self, resource_ref_id: str) -> ResourceRefRecord | None:
        if self.resource_ref is None:
            return None
        return self.resource_ref if self.resource_ref.id == resource_ref_id else None


class _ApprovalRepository:
    def __init__(self) -> None:
        self.records: list[object] = []

    def insert(self, record: object) -> None:
        self.records.append(record)

    def list_by_action(self, action_id: str) -> tuple[object, ...]:
        return tuple(record for record in self.records if record.action_id == action_id)


class _CommandReceiptRepository:
    def __init__(self) -> None:
        self.received: dict[str, dict[str, object]] = {}
        self.finished: dict[str, dict[str, object]] = {}

    def get_by_command_id(self, command_id: str) -> None:
        return None

    def add_received(self, **values: object) -> None:
        self.received[str(values["command_id"])] = dict(values)

    def finish_json(self, **values: object) -> None:
        self.finished[str(values["command_id"])] = dict(values)


class _UnitOfWork:
    def __init__(
        self,
        *,
        action: ActionRecord,
        plan: PlanRecord,
        resource_ref: ResourceRefRecord | None,
    ) -> None:
        self.actions = _ActionRepository(action)
        self.plans = _PlanRepository(plan)
        self.resource_refs = _ResourceRefRepository(resource_ref)
        self.approvals = _ApprovalRepository()
        self.command_receipts = _CommandReceiptRepository()
        self.traces = _Sink()
        self.audits = _Sink()
        self.commit_count = 0

    def __enter__(self) -> "_UnitOfWork":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def commit(self) -> None:
        self.commit_count += 1


def _calendar_conflict() -> dict[str, object]:
    return {
        "decision": "NO_CONFLICT",
        "matched_resource_ids": [],
        "reason_codes": ["NO_CONFLICT"],
        "checked_at_ms": 1000,
        "freshness": "FRESH_GOOGLE_GET",
    }


def _feasibility() -> dict[str, object]:
    return {
        "decision": "FEASIBLE",
        "reason_codes": ["CLEAN_SLOT_AVAILABLE"],
        "business_deadline": "2026-08-25",
        "derived_cutoff": "2026-08-25T18:00:00+09:00",
        "required_duration_minutes": 30,
        "best_clean_slot_minutes": 120,
        "best_warning_slot_minutes": 120,
        "checked_at_ms": 1000,
        "freshness": "FRESH_GOOGLE_GET",
    }


def _make_action(
    *,
    tool_name: str,
    arguments_json: str,
    resource_ref_id: str,
    risk: dict[str, object] | None = None,
) -> ActionRecord:
    return ActionRecord(
        id="action-1",
        plan_id="plan-1",
        connector_id="google_workspace",
        position=1,
        tool_name=tool_name,
        effect_type=EffectType.UPDATE.value,
        approval_requirement="REQUIRED",
        verification_policy="GET_COMPARE",
        recovery_policy="GET_TARGET",
        target_resource_ref_id=resource_ref_id,
        status=ActionStatus.MODIFIED.value,
        arguments_json=arguments_json,
        arguments_hash="a" * 64,
        expected_json="{}",
        risk={} if risk is None else risk,
        version=4,
        created_at_ms=1,
        updated_at_ms=1,
    )


def _make_plan() -> PlanRecord:
    return PlanRecord(
        id="plan-1",
        run_id="run-1",
        revision_no=1,
        status=PlanStatus.WAITING_APPROVAL,
        summary_text=None,
        created_at_ms=1,
        review_status=PlanReviewStatus.PASSED,
        review_version=1,
    )


def _make_resource_ref(
    *,
    source: ResourceSource,
    resource_type: StoredResourceType,
    resource_id: str,
    parent_resource_id: str | None,
    version_token: str | None,
) -> ResourceRefRecord:
    return ResourceRefRecord(
        id="resource-ref-1",
        run_id="run-1",
        connector_id="google_workspace",
        source=source,
        resource_type=resource_type,
        resource_id=resource_id,
        parent_resource_id=parent_resource_id,
        canonical_url=None,
        title=resource_id,
        event_time_ms=None,
        version_token=version_token,
        metadata_json="{}",
        captured_at_ms=1,
    )


def _approve(uow: _UnitOfWork, *, calendar_acknowledged: bool = False):
    handler = ApproveActionHandler(
        unit_of_work_factory=lambda: uow,
        now_ms=lambda: 10_000,
    )
    return handler(
        ApproveActionCommand(
            command_id="command-1",
            request_hash="request-hash",
            action_id="action-1",
            expected_version=4,
            approved_by_account_id="account-1",
            approved_by_display="User",
            approval_id="approval-1",
            idempotency_key="idem-1",
            ttl_ms=60_000,
            calendar_conflict_acknowledged=calendar_acknowledged,
        )
    )


def _persisted_source(uow: _UnitOfWork) -> dict[str, object]:
    assert len(uow.approvals.records) == 1
    return loads(uow.approvals.records[0].source_snapshot_json)


def test_tasks_update_persists_source_resource_authority() -> None:
    action = _make_action(
        tool_name="tasks_update_task",
        arguments_json='{"task_id":"task-42","task_list_id":"list-7","payload":{"title":"Updated"}}',
        resource_ref_id="resource-ref-1",
    )
    resource_ref = _make_resource_ref(
        source=ResourceSource.TASKS,
        resource_type=StoredResourceType.TASK,
        resource_id="task-42",
        parent_resource_id="list-7",
        version_token="task-version-9",
    )
    uow = _UnitOfWork(action=action, plan=_make_plan(), resource_ref=resource_ref)

    result = _approve(uow)

    assert result.applied is True
    assert _persisted_source(uow) == {
        "resource_type": "task",
        "resource_id": "task-42",
        "parent_id": "list-7",
        "version": "task-version-9",
    }


def test_calendar_update_preserves_calendar_conflict_metadata() -> None:
    conflict = _calendar_conflict()
    action = _make_action(
        tool_name="calendar_update_event",
        arguments_json='{"calendar_id":"primary","event_id":"event-7","payload":{"summary":"Updated"}}',
        resource_ref_id="resource-ref-1",
        risk={"calendar_conflict": conflict},
    )
    resource_ref = _make_resource_ref(
        source=ResourceSource.CALENDAR,
        resource_type=StoredResourceType.EVENT,
        resource_id="event-7",
        parent_resource_id="primary",
        version_token='"etag-7"',
    )
    uow = _UnitOfWork(action=action, plan=_make_plan(), resource_ref=resource_ref)

    result = _approve(uow)

    assert result.applied is True
    snapshot = _persisted_source(uow)
    assert snapshot["resource_id"] == "event-7"
    assert snapshot["version"] == '"etag-7"'
    assert snapshot["calendar_conflict"] == {
        "risk": conflict,
        "acknowledged": False,
    }


def test_calendar_update_preserves_feasibility_metadata() -> None:
    feasibility = _feasibility()
    action = _make_action(
        tool_name="calendar_update_event",
        arguments_json='{"calendar_id":"primary","event_id":"event-7","payload":{"summary":"Updated"}}',
        resource_ref_id="resource-ref-1",
        risk={"feasibility": feasibility},
    )
    resource_ref = _make_resource_ref(
        source=ResourceSource.CALENDAR,
        resource_type=StoredResourceType.EVENT,
        resource_id="event-7",
        parent_resource_id="primary",
        version_token="calendar-version-11",
    )
    uow = _UnitOfWork(action=action, plan=_make_plan(), resource_ref=resource_ref)

    result = _approve(uow)

    assert result.applied is True
    snapshot = _persisted_source(uow)
    assert snapshot["resource_type"] == "calendar_event"
    assert snapshot["resource_id"] == "event-7"
    assert snapshot["version"] == "calendar-version-11"
    assert snapshot["feasibility"] == feasibility


def test_calendar_update_preserves_resource_and_both_policy_metadata() -> None:
    conflict = _calendar_conflict()
    feasibility = _feasibility()
    action = _make_action(
        tool_name="calendar_update_event",
        arguments_json='{"calendar_id":"primary","event_id":"event-7","payload":{"summary":"Updated"}}',
        resource_ref_id="resource-ref-1",
        risk={
            "calendar_conflict": conflict,
            "feasibility": feasibility,
        },
    )
    resource_ref = _make_resource_ref(
        source=ResourceSource.CALENDAR,
        resource_type=StoredResourceType.EVENT,
        resource_id="event-7",
        parent_resource_id="primary",
        version_token="calendar-version-12",
    )
    uow = _UnitOfWork(action=action, plan=_make_plan(), resource_ref=resource_ref)

    result = _approve(uow)

    assert result.applied is True
    snapshot = _persisted_source(uow)
    assert snapshot["resource_id"] == "event-7"
    assert snapshot["parent_id"] == "primary"
    assert snapshot["version"] == "calendar-version-12"
    assert snapshot["calendar_conflict"]["risk"] == conflict
    assert snapshot["feasibility"] == feasibility


def test_policy_metadata_cannot_overwrite_source_resource_authority() -> None:
    with pytest.raises(
        PolicyViolationError,
        match="cannot overwrite source resource authority",
    ):
        merge_approval_snapshot_metadata(
            {
                "resource_type": "task",
                "resource_id": "task-42",
                "version": "v1",
            },
            {"version": "forged-policy-version"},
        )


@pytest.mark.parametrize(
    ("resource_ref", "expected_detail"),
    [
        (
            _make_resource_ref(
                source=ResourceSource.TASKS,
                resource_type=StoredResourceType.TASK,
                resource_id="task-42",
                parent_resource_id="list-7",
                version_token=None,
            ),
            "resource version is missing",
        ),
        (
            _make_resource_ref(
                source=ResourceSource.TASKS,
                resource_type=StoredResourceType.TASK,
                resource_id="different-task",
                parent_resource_id="list-7",
                version_token="v1",
            ),
            "resource id does not match action arguments",
        ),
    ],
)
def test_tasks_update_missing_or_stale_source_authority_fails_closed(
    resource_ref: ResourceRefRecord,
    expected_detail: str,
) -> None:
    action = _make_action(
        tool_name="tasks_update_task",
        arguments_json='{"task_id":"task-42","task_list_id":"list-7","payload":{"title":"Updated"}}',
        resource_ref_id="resource-ref-1",
    )
    uow = _UnitOfWork(action=action, plan=_make_plan(), resource_ref=resource_ref)

    result = _approve(uow)

    assert result.applied is False
    assert result.result_code == ResultCode.STATE_CONFLICT.value
    assert expected_detail in (result.conflict_detail or "")
    assert uow.approvals.records == []
    assert uow.actions.action.status == ActionStatus.MODIFIED.value


def test_gmail_update_draft_persists_source_identity_and_version() -> None:
    action = _make_action(
        tool_name="gmail_update_draft",
        arguments_json='{"draft_id":"draft-9","payload":{"subject":"Updated"}}',
        resource_ref_id="resource-ref-1",
    )
    resource_ref = _make_resource_ref(
        source=ResourceSource.GMAIL,
        resource_type=StoredResourceType.MESSAGE,
        resource_id="draft-9",
        parent_resource_id="thread-3",
        version_token="gmail-version-4",
    )
    uow = _UnitOfWork(action=action, plan=_make_plan(), resource_ref=resource_ref)

    result = _approve(uow)

    assert result.applied is True
    assert _persisted_source(uow) == {
        "resource_type": "gmail_draft",
        "resource_id": "draft-9",
        "parent_id": "thread-3",
        "version": "gmail-version-4",
    }
