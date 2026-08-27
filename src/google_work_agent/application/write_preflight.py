"""Provider-read safety checks performed before a write claim."""

from __future__ import annotations

import time
from collections.abc import Callable
from json import loads
from typing import Protocol

from google_work_agent.application.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
    CalendarConflictGateway,
    CalendarConflictValidator,
    approval_calendar_conflict_authority,
    calendar_conflict_authority,
    calendar_conflict_change_requires_reapproval,
    merge_calendar_conflict_risk,
)
from google_work_agent.application.feasibility import (
    FeasibilityGateway,
    FeasibilityValidator,
    approval_feasibility_authority,
    feasibility_authority,
    feasibility_change_requires_reapproval,
    merge_feasibility_risk,
)
from google_work_agent.application.policy_kernels.calendar_conflict import CalendarWorkHours
from google_work_agent.application.task_duplicates import (
    TASK_CREATE_TOOL,
    TaskDuplicateValidator,
    TaskListGateway,
    approval_duplicate_authority,
    duplicate_authority,
    duplicate_change_requires_reapproval,
    merge_duplicate_risk,
)
from google_work_agent.application.write_action_arguments import (
    dict_argument as _dict_argument,
)
from google_work_agent.application.write_action_arguments import (
    required_argument_string as _required_argument_string,
)
from google_work_agent.application.write_persistence import (
    audit_event as _audit_event,
)
from google_work_agent.application.write_persistence import (
    require_action as _require_action,
)
from google_work_agent.application.write_persistence import (
    require_plan as _require_plan,
)
from google_work_agent.application.write_persistence import revoke_active_approvals
from google_work_agent.domain.action.model import ActionStatusV1, EffectType, PolicyViolationError
from google_work_agent.domain.action.transitions.modify_action import transition_modify_action
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord
from google_work_agent.ports import (
    GoogleWorkspaceGatewayError,
    ResourceSnapshot,
    ResourceType,
    UnitOfWork,
)
from google_work_agent.ports.connector.migration_contracts.tool_registry import (
    build_p0_tool_registry,
)


def _calendar_conflict_audit_metadata(
    *, risk: dict[str, object], action_id: str
) -> dict[str, object]:
    authority = calendar_conflict_authority(risk) or ("UNKNOWN", ())
    value = risk.get("calendar_conflict")
    return {
        "action_id": action_id,
        "decision": authority[0],
        "matched_resource_ids": list(authority[1]),
        "reason_codes": value.get("reason_codes", []) if isinstance(value, dict) else [],
        "freshness": value.get("freshness", "UNKNOWN")
        if isinstance(value, dict)
        else "UNKNOWN",
    }


def _feasibility_audit_metadata(risk: dict[str, object]) -> dict[str, object]:
    value = risk.get("feasibility")
    authority = feasibility_authority(risk)
    return {
        "decision": authority[0] if authority is not None else "UNKNOWN",
        "reason_codes": value.get("reason_codes", []) if isinstance(value, dict) else [],
        "required_duration": (
            value.get("required_duration_minutes") if isinstance(value, dict) else None
        ),
        "freshness": value.get("freshness", "UNKNOWN")
        if isinstance(value, dict)
        else "UNKNOWN",
    }


class PreflightWriteGateway(
    TaskListGateway,
    CalendarConflictGateway,
    FeasibilityGateway,
    Protocol,
):
    """Provider reads required by write preflight safety checks."""

    def get_gmail_draft(self, *, draft_id: str) -> ResourceSnapshot: ...

    def get_task(self, *, task_list_id: str, task_id: str) -> ResourceSnapshot: ...


class PreflightWriteActionService:
    """Read the approved target immediately before the claim transaction."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        gateway: PreflightWriteGateway,
        now_ms: Callable[[], int] | None = None,
        work_hours_provider: Callable[[], CalendarWorkHours] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._gateway = gateway
        self._now_ms = now_ms or (lambda: time.time_ns() // 1_000_000)
        self._registry = build_p0_tool_registry()
        self._task_duplicates = TaskDuplicateValidator(gateway=gateway, now_ms=self._now_ms)
        self._calendar_conflicts = CalendarConflictValidator(
            gateway=gateway,
            now_ms=self._now_ms,
            work_hours_provider=work_hours_provider
            or (lambda: CalendarWorkHours(timezone="Asia/Seoul")),
        )
        self._feasibility = FeasibilityValidator(
            gateway=gateway,
            now_ms=self._now_ms,
            work_hours_provider=work_hours_provider
            or (lambda: CalendarWorkHours(timezone="Asia/Seoul")),
        )

    def __call__(self, *, action_id: str) -> dict[str, object]:
        with self._unit_of_work_factory() as unit_of_work:
            action = _require_action(unit_of_work, action_id)
            if action.status != ActionStatusV1.APPROVED.value:
                raise PolicyViolationError("write preflight requires an approved action")
            self._registry.require(action.tool_name)
            arguments = _dict_argument(loads(action.arguments_json))
            action_version = action.version
            arguments_hash = action.arguments_hash
            plan = _require_plan(unit_of_work, action.plan_id)
            approval = unit_of_work.approvals.get_active_by_action(action.id)
            if approval is None:
                raise PolicyViolationError("write preflight requires an active approval")
            approval_id = approval.id
            approval_snapshot = _dict_argument(loads(approval.source_snapshot_json))
            target_ref = (
                None
                if action.target_resource_ref_id is None
                else unit_of_work.resource_refs.get(action.target_resource_ref_id)
            )

        if action.tool_name == "gmail_update_draft":
            draft_id = _required_argument_string(arguments, "draft_id")
            draft = self._gateway.get_gmail_draft(draft_id=draft_id)
            validate_preflight_target(
                snapshot=draft,
                target_ref=target_ref,
                expected_resource_type=ResourceType.GMAIL_DRAFT,
                expected_parent_id=None,
                require_target_ref=True,
                require_version_token=True,
            )
            return _update_source_snapshot(draft)

        if action.tool_name == "tasks_update_task":
            task_list_id = _required_argument_string(arguments, "task_list_id")
            task_id = _required_argument_string(arguments, "task_id")
            task = self._gateway.get_task(task_list_id=task_list_id, task_id=task_id)
            validate_preflight_target(
                snapshot=task,
                target_ref=target_ref,
                expected_resource_type=ResourceType.TASK,
                expected_parent_id=task_list_id,
                require_target_ref=True,
                require_version_token=True,
            )
            return _update_source_snapshot(task)

        update_source_snapshot: dict[str, object] = {}
        if action.tool_name == "calendar_update_event":
            calendar_id = _required_argument_string(arguments, "calendar_id")
            event_id = _required_argument_string(arguments, "event_id")
            event = self._gateway.get_calendar_event(calendar_id=calendar_id, event_id=event_id)
            validate_preflight_target(
                snapshot=event,
                target_ref=target_ref,
                expected_resource_type=ResourceType.CALENDAR_EVENT,
                expected_parent_id=calendar_id,
                require_target_ref=True,
                require_version_token=True,
            )
            update_source_snapshot = _update_source_snapshot(event)

        if action.tool_name == TASK_CREATE_TOOL:
            try:
                fresh_duplicate_risk = self._task_duplicates.fresh_risk(arguments)
            except Exception as error:
                with self._unit_of_work_factory() as unit_of_work:
                    current = _require_action(unit_of_work, action_id)
                    unit_of_work.audits.add(
                        _audit_event(
                            run_id=plan.run_id,
                            action_id=action_id,
                            event_type="TASK_DUPLICATE_PREFLIGHT_BLOCKED",
                            outcome="FAIL_CLOSED",
                            metadata={
                                "action_version": current.version,
                                "safe_error_code": (
                                    error.code.value
                                    if isinstance(error, GoogleWorkspaceGatewayError)
                                    else type(error).__name__
                                ),
                            },
                            created_at_ms=self._now_ms(),
                        )
                    )
                    unit_of_work.commit()
                raise

            must_reapprove = False
            with self._unit_of_work_factory() as unit_of_work:
                current = _require_action(unit_of_work, action_id)
                current_plan = _require_plan(unit_of_work, current.plan_id)
                latest_plan = max(
                    unit_of_work.plans.list_by_run(current_plan.run_id),
                    key=lambda candidate: getattr(candidate, "revision_no", 0),
                    default=None,
                )
                current_approval = unit_of_work.approvals.get_active_by_action(action_id)
                if (
                    current.status != ActionStatusV1.APPROVED.value
                    or current.version != action_version
                    or current.arguments_hash != arguments_hash
                    or current_approval is None
                    or current_approval.id != approval_id
                ):
                    raise PolicyViolationError(
                        "write action changed during task duplicate preflight"
                    )
                merged_risk = merge_duplicate_risk(current.risk, fresh_duplicate_risk)
                must_reapprove = duplicate_change_requires_reapproval(
                    approved=approval_duplicate_authority(approval_snapshot),
                    current=duplicate_authority(merged_risk),
                )
                now_ms = self._now_ms()
                if must_reapprove:
                    revoke_active_approvals(unit_of_work, current.id)
                    result = transition_modify_action(
                        ActionStatusV1(current.status),
                        current.version,
                        current.version,
                        effect_type=EffectType(current.effect_type),
                        plan_status=current_plan.status,
                        plan_is_current=(
                            latest_plan is not None and latest_plan.id == current_plan.id
                        ),
                    )
                    if (
                        not result.applied
                        or unit_of_work.actions.update_if_version_and_status(
                            current.id,
                            expected_version=current.version,
                            expected_status=ActionStatusV1(current.status),
                            next_status=result.current_status,
                            updated_at_ms=now_ms,
                            arguments_json=current.arguments_json,
                            arguments_hash=current.arguments_hash,
                            risk=merged_risk,
                        )
                        is None
                    ):
                        raise PolicyViolationError(
                            "write action changed during task duplicate preflight"
                        )
                    unit_of_work.audits.add(
                        _audit_event(
                            run_id=plan.run_id,
                            action_id=current.id,
                            event_type="TASK_DUPLICATE_PREFLIGHT_BLOCKED",
                            outcome="REAPPROVAL_REQUIRED",
                            metadata={
                                "decision": (duplicate_authority(merged_risk) or ("UNKNOWN", ()))[
                                    0
                                ],
                                "matched_count": len(
                                    (duplicate_authority(merged_risk) or ("UNKNOWN", ()))[1]
                                ),
                            },
                            created_at_ms=now_ms,
                        )
                    )
                else:
                    if (
                        unit_of_work.actions.update_if_version_and_status(
                            current.id,
                            expected_version=current.version,
                            expected_status=ActionStatusV1(current.status),
                            next_status=ActionStatusV1(current.status),
                            updated_at_ms=now_ms,
                            risk=merged_risk,
                        )
                        is None
                    ):
                        raise PolicyViolationError(
                            "write action changed during duplicate preflight"
                        )
                authority = duplicate_authority(merged_risk) or ("UNKNOWN", ())
                unit_of_work.audits.add(
                    _audit_event(
                        run_id=plan.run_id,
                        action_id=current.id,
                        event_type="TASK_DUPLICATE_CHECKED",
                        outcome=("BLOCKED" if must_reapprove else "ALLOWED"),
                        metadata={
                            "decision": authority[0],
                            "matched_count": len(authority[1]),
                            "freshness": "FRESH_GOOGLE_GET",
                        },
                        created_at_ms=now_ms,
                    )
                )
                unit_of_work.commit()
            if must_reapprove:
                raise PolicyViolationError(
                    "task duplicate result changed; acknowledgement and reapproval are required"
                )
            return {}

        if action.tool_name in CALENDAR_CONFLICT_TOOLS:
            try:
                fresh_conflict_risk = self._calendar_conflicts.fresh_risk(arguments)
                fresh_feasibility_risk = self._feasibility.fresh_risk(
                    arguments=arguments, risk=action.risk
                )
            except Exception as error:
                with self._unit_of_work_factory() as unit_of_work:
                    current = _require_action(unit_of_work, action_id)
                    unit_of_work.audits.add(
                        _audit_event(
                            run_id=plan.run_id,
                            action_id=action_id,
                            event_type="CALENDAR_CONFLICT_PREFLIGHT_BLOCKED",
                            outcome="FAIL_CLOSED",
                            metadata={
                                "action_version": current.version,
                                "safe_error_code": (
                                    error.code.value
                                    if isinstance(error, GoogleWorkspaceGatewayError)
                                    else type(error).__name__
                                ),
                            },
                            created_at_ms=self._now_ms(),
                        )
                    )
                    unit_of_work.commit()
                raise

            must_reapprove = False
            with self._unit_of_work_factory() as unit_of_work:
                current = _require_action(unit_of_work, action_id)
                current_plan = _require_plan(unit_of_work, current.plan_id)
                latest_plan = max(
                    unit_of_work.plans.list_by_run(current_plan.run_id),
                    key=lambda candidate: getattr(candidate, "revision_no", 0),
                    default=None,
                )
                current_approval = unit_of_work.approvals.get_active_by_action(action_id)
                if (
                    current.status != ActionStatusV1.APPROVED.value
                    or current.version != action_version
                    or current.arguments_hash != arguments_hash
                    or current_approval is None
                    or current_approval.id != approval_id
                ):
                    raise PolicyViolationError(
                        "write action changed during calendar conflict preflight"
                    )
                merged_risk = merge_calendar_conflict_risk(current.risk, fresh_conflict_risk)
                merged_risk = merge_feasibility_risk(merged_risk, fresh_feasibility_risk)
                must_reapprove = calendar_conflict_change_requires_reapproval(
                    approved=approval_calendar_conflict_authority(approval_snapshot),
                    current=calendar_conflict_authority(merged_risk),
                ) or feasibility_change_requires_reapproval(
                    approved=approval_feasibility_authority(approval_snapshot),
                    current=feasibility_authority(merged_risk),
                )
                now_ms = self._now_ms()
                if must_reapprove:
                    revoke_active_approvals(unit_of_work, current.id)
                    result = transition_modify_action(
                        ActionStatusV1(current.status),
                        current.version,
                        current.version,
                        effect_type=EffectType(current.effect_type),
                        plan_status=current_plan.status,
                        plan_is_current=(
                            latest_plan is not None and latest_plan.id == current_plan.id
                        ),
                    )
                    if (
                        not result.applied
                        or unit_of_work.actions.update_if_version_and_status(
                            current.id,
                            expected_version=current.version,
                            expected_status=ActionStatusV1(current.status),
                            next_status=result.current_status,
                            updated_at_ms=now_ms,
                            arguments_json=current.arguments_json,
                            arguments_hash=current.arguments_hash,
                            risk=merged_risk,
                        )
                        is None
                    ):
                        raise PolicyViolationError(
                            "write action changed during calendar conflict preflight"
                        )
                else:
                    if (
                        unit_of_work.actions.update_if_version_and_status(
                            current.id,
                            expected_version=current.version,
                            expected_status=ActionStatusV1(current.status),
                            next_status=ActionStatusV1(current.status),
                            updated_at_ms=now_ms,
                            risk=merged_risk,
                        )
                        is None
                    ):
                        raise PolicyViolationError(
                            "write action changed during calendar conflict preflight"
                        )
                unit_of_work.audits.add(
                    _audit_event(
                        run_id=plan.run_id,
                        action_id=current.id,
                        event_type="CALENDAR_CONFLICT_CHECKED",
                        outcome="REAPPROVAL_REQUIRED" if must_reapprove else "ALLOWED",
                        metadata={
                            **_calendar_conflict_audit_metadata(
                                risk=merged_risk, action_id=current.id
                            ),
                        },
                        created_at_ms=now_ms,
                    )
                )
                if feasibility_authority(merged_risk) is not None:
                    unit_of_work.audits.add(
                        _audit_event(
                            run_id=plan.run_id,
                            action_id=current.id,
                            event_type="FEASIBILITY_CHECKED",
                            outcome="REAPPROVAL_REQUIRED" if must_reapprove else "ALLOWED",
                            metadata=_feasibility_audit_metadata(merged_risk),
                            created_at_ms=now_ms,
                        )
                    )
                unit_of_work.commit()
            if must_reapprove:
                raise PolicyViolationError(
                    "calendar conflict result changed; acknowledgement and reapproval are required"
                )
            return update_source_snapshot

        if action.tool_name == "gmail_send":
            draft_id = _required_argument_string(arguments, "draft_id")
            draft = self._gateway.get_gmail_draft(draft_id=draft_id)
            validate_preflight_target(
                snapshot=draft,
                target_ref=None,
                expected_resource_type=ResourceType.GMAIL_DRAFT,
                expected_parent_id=None,
            )
            return {}
        if action.tool_name == "calendar_delete_event":
            calendar_id = _required_argument_string(arguments, "calendar_id")
            event_id = _required_argument_string(arguments, "event_id")
            if arguments.get("delete_scope") not in {None, "SINGLE"}:
                raise PolicyViolationError("calendar recurring series deletion is forbidden")
            event = self._gateway.get_calendar_event(calendar_id=calendar_id, event_id=event_id)
            if (
                event.payload.get("recurring_event_id") is not None
                and arguments.get("delete_scope") != "SINGLE"
            ):
                raise PolicyViolationError("recurring event series deletion is forbidden")
            validate_preflight_target(
                snapshot=event,
                target_ref=target_ref,
                expected_resource_type=ResourceType.CALENDAR_EVENT,
                expected_parent_id=calendar_id,
            )
        if action.tool_name == "tasks_delete_task":
            task_list_id = _required_argument_string(arguments, "task_list_id")
            task_id = _required_argument_string(arguments, "task_id")
            task = self._gateway.get_task(task_list_id=task_list_id, task_id=task_id)
            validate_preflight_target(
                snapshot=task,
                target_ref=target_ref,
                expected_resource_type=ResourceType.TASK,
                expected_parent_id=task_list_id,
            )
        return {}


def _update_source_snapshot(snapshot: ResourceSnapshot) -> dict[str, object]:
    """Project a fresh provider read onto the Approval integrity surface."""

    result: dict[str, object] = {
        "resource_type": snapshot.resource_type.value,
        "resource_id": snapshot.resource_id,
        "version": snapshot.version,
    }
    if snapshot.parent_id is not None:
        result["parent_id"] = snapshot.parent_id
    return result


def validate_preflight_target(
    *,
    snapshot: ResourceSnapshot,
    target_ref: ResourceRefRecord | None,
    expected_resource_type: ResourceType,
    expected_parent_id: str | None,
    require_target_ref: bool = False,
    require_version_token: bool = False,
) -> None:
    if snapshot.resource_type is not expected_resource_type:
        raise PolicyViolationError("preflight target resource type mismatch")
    if expected_parent_id is not None and snapshot.parent_id != expected_parent_id:
        raise PolicyViolationError("preflight target parent mismatch")
    if target_ref is None:
        if require_target_ref:
            raise PolicyViolationError("write update requires a persisted target reference")
        if expected_resource_type is ResourceType.CALENDAR_EVENT:
            raise PolicyViolationError("calendar delete requires a persisted target reference")
        if expected_resource_type is ResourceType.TASK:
            raise PolicyViolationError("task delete requires a persisted target reference")
        return
    if target_ref.resource_id != snapshot.resource_id:
        raise PolicyViolationError("preflight target identity mismatch")
    if require_version_token and target_ref.version_token is None:
        raise PolicyViolationError("write update requires a persisted target version")
    if target_ref.version_token is not None and target_ref.version_token != snapshot.version:
        raise PolicyViolationError("preflight target version mismatch")
    if (
        target_ref.parent_resource_id is not None
        and target_ref.parent_resource_id != snapshot.parent_id
    ):
        raise PolicyViolationError("preflight target parent reference mismatch")
