"""Claim-owner-local provider-read safety checks before a write claim."""

from __future__ import annotations

import time
from collections.abc import Callable
from json import loads
from typing import Literal, Protocol, cast

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.action.calendar_conflict_policy import (
    CalendarWorkHours,
)
from google_work_agent.application.use_cases.action.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
    CalendarConflictGateway,
    CalendarConflictValidator,
    approval_calendar_conflict_authority,
    approval_source_snapshot_for_calendar_conflict,
    calendar_conflict_authority,
    calendar_conflict_change_requires_reapproval,
    merge_calendar_conflict_risk,
)
from google_work_agent.application.use_cases.action.evaluate_action_policy import (
    EvaluateActionPolicyHandler,
    EvaluateActionPolicyQueryV1,
)
from google_work_agent.application.use_cases.action.feasibility import (
    FeasibilityGateway,
    FeasibilityValidator,
    approval_feasibility_authority,
    approval_source_snapshot_for_feasibility,
    feasibility_authority,
    feasibility_change_requires_reapproval,
    merge_feasibility_risk,
)
from google_work_agent.application.use_cases.action.persistence_cas import update_action_record
from google_work_agent.application.use_cases.action.policy import count_independent_evidence
from google_work_agent.application.use_cases.action.refresh_expired_action import (
    RefreshExpiredActionCommand,
    RefreshExpiredActionHandler,
)
from google_work_agent.application.use_cases.action.task_duplicates import (
    TASK_CREATE_TOOL,
    TaskDuplicateValidator,
    TaskListGateway,
    approval_duplicate_authority,
    approval_source_snapshot_for_task_duplicate,
    duplicate_authority,
    duplicate_change_requires_reapproval,
    merge_duplicate_risk,
)
from google_work_agent.application.use_cases.action.write_action_arguments import (
    dict_argument as _dict_argument,
)
from google_work_agent.application.use_cases.action.write_action_arguments import (
    required_argument_string as _required_argument_string,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    audit_event as _audit_event,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    require_action as _require_action,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    require_plan as _require_plan,
)
from google_work_agent.application.use_cases.approval.expire_approval import (
    ExpireApprovalCommand,
    ExpireApprovalHandler,
)
from google_work_agent.application.use_cases.run.block_run import BlockRunCommand, BlockRunHandler
from google_work_agent.domain.action.model import ActionStatusV1, EffectType, PolicyViolationError
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord
from google_work_agent.ports.connector.contracts.google_workspace import (
    GoogleWorkspaceGatewayError,
    ResourceSnapshot,
    ResourceType,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


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
        "freshness": value.get("freshness", "UNKNOWN") if isinstance(value, dict) else "UNKNOWN",
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
        "freshness": value.get("freshness", "UNKNOWN") if isinstance(value, dict) else "UNKNOWN",
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


class _WritePreflight:
    """Read the approved target immediately before the claim transaction."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        gateway: PreflightWriteGateway,
        now_ms: Callable[[], int] | None = None,
        work_hours_provider: Callable[[], CalendarWorkHours] | None = None,
        expire_approval: ExpireApprovalHandler | None = None,
        refresh_expired_action: RefreshExpiredActionHandler | None = None,
        block_run: BlockRunHandler | None = None,
        tool_registry: SignedToolRegistry,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._gateway = gateway
        self._now_ms = now_ms or (lambda: time.time_ns() // 1_000_000)
        self._registry = tool_registry
        self._evaluate_action_policy = EvaluateActionPolicyHandler()
        self._expire_approval = expire_approval
        self._refresh_expired_action = refresh_expired_action
        self._block_run = block_run
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
            registry_entry = self._registry.get_required(action.connector_id, action.tool_name)
            arguments = _dict_argument(loads(action.arguments_json))
            action_version = action.version
            arguments_hash = action.arguments_hash
            plan = _require_plan(unit_of_work, action.plan_id)
            approval = unit_of_work.approvals.get_active_for_action(action.id)
            if approval is None:
                raise PolicyViolationError("write preflight requires an active approval")
            approval_id = approval.id
            approval_snapshot = _dict_argument(loads(approval.source_snapshot_json))
            evidence = tuple(unit_of_work.evidence.list_for_action(action.id))
            target_ref = (
                None
                if action.target_resource_ref_id is None
                else unit_of_work.resource_refs.get(action.target_resource_ref_id)
            )

        policy = self._evaluate_action_policy(
            EvaluateActionPolicyQueryV1(
                schema_version=1,
                run_id=plan.run_id,
                action_id=action.id,
                action_version=action.version,
                tool_id=action.tool_name,
                effect=cast(
                    Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"],
                    action.effect_type,
                ),
                arguments_hash=action.arguments_hash,
                source_snapshot_ref=approval.source_snapshot_hash,
                policy_version=registry_entry.registry_version,
                required_scopes_granted=True,
                evidence_count=len(evidence),
                evidence_refs=tuple(sorted(str(item.id) for item in evidence)),
                independent_evidence_count=count_independent_evidence(evidence),
                target_is_user_selected=(
                    action.effect_type not in {EffectType.UPDATE.value, EffectType.DELETE.value}
                    or target_ref is not None
                ),
                has_explicit_resource_relation=target_ref is not None,
            )
        )
        if policy.decision != "ALLOW":
            raise PolicyViolationError(",".join(policy.reason_codes))

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
                    unit_of_work.audits.append(
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
                current_approval = unit_of_work.approvals.get_active_for_action(action_id)
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
                if (
                    not must_reapprove
                    and update_action_record(
                        unit_of_work,
                        current.id,
                        expected_version=current.version,
                        expected_status=ActionStatusV1(current.status),
                        next_status=ActionStatusV1(current.status),
                        updated_at_ms=now_ms,
                        risk=merged_risk,
                    )
                    is None
                ):
                    raise PolicyViolationError("write action changed during duplicate preflight")
                authority = duplicate_authority(merged_risk) or ("UNKNOWN", ())
                unit_of_work.audits.append(
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
                fresh_snapshot = approval_source_snapshot_for_task_duplicate(
                    risk=merged_risk, acknowledged=False
                )
                self._expire_and_refresh(
                    action_id=action_id,
                    approval_id=approval_id,
                    expected_action_version=action_version,
                    current_source_snapshot=fresh_snapshot,
                    current_policy_version=registry_entry.registry_version,
                    current_tool_schema_version=registry_entry.input_schema_version,
                    fresh_risk=merged_risk,
                )
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
                    unit_of_work.audits.append(
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
                current_approval = unit_of_work.approvals.get_active_for_action(action_id)
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
                policy_denied = (feasibility_authority(merged_risk) or (None,))[0] == "INFEASIBLE"
                now_ms = self._now_ms()
                if (not must_reapprove or policy_denied) and update_action_record(
                    unit_of_work,
                    current.id,
                    expected_version=current.version,
                    expected_status=ActionStatusV1(current.status),
                    next_status=ActionStatusV1(current.status),
                    updated_at_ms=now_ms,
                    risk=merged_risk,
                ) is None:
                    raise PolicyViolationError(
                        "write action changed during calendar conflict preflight"
                    )
                unit_of_work.audits.append(
                    _audit_event(
                        run_id=plan.run_id,
                        action_id=current.id,
                        event_type="CALENDAR_CONFLICT_CHECKED",
                        outcome=(
                            "BLOCKED"
                            if policy_denied
                            else "REAPPROVAL_REQUIRED"
                            if must_reapprove
                            else "ALLOWED"
                        ),
                        metadata={
                            **_calendar_conflict_audit_metadata(
                                risk=merged_risk, action_id=current.id
                            ),
                        },
                        created_at_ms=now_ms,
                    )
                )
                if feasibility_authority(merged_risk) is not None:
                    unit_of_work.audits.append(
                        _audit_event(
                            run_id=plan.run_id,
                            action_id=current.id,
                            event_type="FEASIBILITY_CHECKED",
                            outcome=(
                                "BLOCKED"
                                if policy_denied
                                else "REAPPROVAL_REQUIRED"
                                if must_reapprove
                                else "ALLOWED"
                            ),
                            metadata=_feasibility_audit_metadata(merged_risk),
                            created_at_ms=now_ms,
                        )
                    )
                unit_of_work.commit()
            if policy_denied:
                self._block_current_run(
                    run_id=plan.run_id,
                    action_id=action_id,
                    reason_code="PREFLIGHT_FEASIBILITY_DENIED",
                )
                raise PolicyViolationError("FEASIBILITY_BLOCKED")
            if must_reapprove:
                fresh_snapshot = {
                    **update_source_snapshot,
                    **approval_source_snapshot_for_calendar_conflict(
                        risk=merged_risk, acknowledged=False
                    ),
                    **approval_source_snapshot_for_feasibility(risk=merged_risk),
                }
                self._expire_and_refresh(
                    action_id=action_id,
                    approval_id=approval_id,
                    expected_action_version=action_version,
                    current_source_snapshot=fresh_snapshot,
                    current_policy_version=registry_entry.registry_version,
                    current_tool_schema_version=registry_entry.input_schema_version,
                    fresh_risk=merged_risk,
                )
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

    def _expire_and_refresh(
        self,
        *,
        action_id: str,
        approval_id: str,
        expected_action_version: int,
        current_source_snapshot: dict[str, object],
        current_policy_version: str,
        current_tool_schema_version: str,
        fresh_risk: dict[str, object],
    ) -> None:
        if self._expire_approval is None or self._refresh_expired_action is None:
            raise RuntimeError("write preflight stale-approval lifecycle is not configured")
        current_source_snapshot_hash = calculate_canonical_json_hash(current_source_snapshot)
        expire_request = {
            "approval_id": approval_id,
            "expected_action_version": expected_action_version,
            "current_source_snapshot": current_source_snapshot,
        }
        expired = self._expire_approval(
            ExpireApprovalCommand(
                command_id=f"system:preflight-expire:{approval_id}",
                request_hash=calculate_canonical_json_hash(expire_request),
                approval_id=approval_id,
                expected_action_version=expected_action_version,
                current_source_snapshot=current_source_snapshot,
            )
        )
        if not expired.applied:
            raise PolicyViolationError(
                expired.conflict_detail or "approval could not be expired during preflight"
            )
        refresh_request = {
            "action_id": action_id,
            "expected_version": expired.action_version,
            "fresh_source_snapshot": current_source_snapshot,
            "fresh_source_snapshot_hash": current_source_snapshot_hash,
            "fresh_policy_version": current_policy_version,
            "fresh_tool_schema_version": current_tool_schema_version,
            "fresh_risk": fresh_risk,
        }
        refreshed = self._refresh_expired_action(
            RefreshExpiredActionCommand(
                command_id=f"system:preflight-refresh:{approval_id}",
                request_hash=calculate_canonical_json_hash(refresh_request),
                action_id=action_id,
                expected_version=expired.action_version,
                fresh_source_snapshot=current_source_snapshot,
                fresh_source_snapshot_hash=current_source_snapshot_hash,
                fresh_policy_version=current_policy_version,
                fresh_tool_schema_version=current_tool_schema_version,
                fresh_risk=fresh_risk,
            )
        )
        if not refreshed.applied:
            raise PolicyViolationError(
                refreshed.conflict_detail or "expired action could not be refreshed"
            )

    def _block_current_run(self, *, run_id: str, action_id: str, reason_code: str) -> None:
        if self._block_run is None:
            raise RuntimeError("write preflight policy-denial lifecycle is not configured")
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(run_id)
        if run is None:
            raise LookupError(f"run not found: {run_id}")
        request = {
            "run_id": run_id,
            "expected_version": run.version,
            "reason_code": reason_code,
            "action_id": action_id,
            "policy_origin": True,
        }
        result = self._block_run(
            BlockRunCommand(
                command_id=f"system:preflight-block:{action_id}:{run.version}",
                request_hash=calculate_canonical_json_hash(request),
                run_id=run_id,
                expected_version=run.version,
                reason_code=reason_code,
                policy_origin=True,
            )
        )
        if not result.applied:
            raise PolicyViolationError(result.conflict_detail or "Run could not be blocked")


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
