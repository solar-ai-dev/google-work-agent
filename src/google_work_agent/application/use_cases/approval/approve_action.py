"""Canonical application use case for explicit Action approval authorization."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from json import dumps, loads

from google_work_agent.application.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
    approval_source_snapshot_for_calendar_conflict,
    require_calendar_conflict_acknowledgement,
)
from google_work_agent.application.feasibility import (
    approval_source_snapshot_for_feasibility,
    require_feasibility_approval,
)
from google_work_agent.application.task_duplicates import (
    TASK_CREATE_TOOL,
    approval_source_snapshot_for_task_duplicate,
    require_duplicate_acknowledgement,
)
from google_work_agent.application.approval_source_snapshot import (
    build_approval_source_snapshot,
    merge_approval_snapshot_metadata,
)
from google_work_agent.application.write_execution_integrity import calculate_recovery_fingerprint
from google_work_agent.application.write_persistence import (
    audit_event,
    emit_command_rejected_hash_mismatch,
)
from google_work_agent.domain import (
    ActionStatus,
    ApprovalStatus,
    CalendarConflictDecision,
    EffectType,
    PolicyViolationError,
    ResultCode,
    build_p0_tool_registry,
    calculate_canonical_json_hash,
    canonicalize_json_value,
    next_allowed_action_commands,
)
from google_work_agent.ports import (
    ActionRecord,
    ApprovalRecord,
    CommandReceiptRecord,
    CommandReceiptStatus,
    PlanReviewStatus,
    PlanStatus,
    TraceEventRecord,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ApproveActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    approved_by_account_id: str
    approved_by_display: str | None
    approval_id: str
    idempotency_key: str
    ttl_ms: int
    duplicate_acknowledged: bool = False
    calendar_conflict_acknowledged: bool = False


@dataclass(frozen=True, slots=True)
class ApproveActionResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    approval_id: str | None = None
    request_replayed: bool = False
    conflict_detail: str | None = None


class ApproveActionHandler:
    """Create one durable Approval from server-owned Action/source authority."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._registry = build_p0_tool_registry()

    def __call__(self, command: ApproveActionCommand) -> ApproveActionResult:
        if command.ttl_ms <= 0:
            raise ValueError("approval ttl must be positive")

        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._resolve_existing_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    command=command,
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="ApproveAction",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )

            action = unit_of_work.actions.get_by_id(command.action_id)
            if action is None:
                raise LookupError(f"action not found: {command.action_id}")
            plan = unit_of_work.plans.get_by_id(action.plan_id)
            if plan is None:
                raise LookupError(f"plan not found: {action.plan_id}")
            entry = self._registry.require(action.tool_name)

            if plan.review_status is not PlanReviewStatus.PASSED:
                return self._reject(
                    unit_of_work=unit_of_work,
                    command=command,
                    action=action,
                    plan_run_id=plan.run_id,
                    now_ms=now_ms,
                    detail="plan review must pass after the latest action modification",
                    event_type="PLAN_REVIEW_APPROVAL_BLOCKED",
                )

            if action.version != command.expected_version:
                response = self._result(
                    action=action,
                    applied=False,
                    result_code=ResultCode.VERSION_CONFLICT,
                    conflict_detail=(
                        f"expected action version {command.expected_version}, "
                        f"current version is {action.version}"
                    ),
                )
                self._finish_receipt(
                    unit_of_work,
                    command.command_id,
                    response,
                    action.version,
                    now_ms,
                )
                unit_of_work.commit()
                return response

            try:
                resource_ref = (
                    None
                    if action.target_resource_ref_id is None
                    else unit_of_work.resource_refs.get_by_id(action.target_resource_ref_id)
                )
                approval_source_snapshot = build_approval_source_snapshot(
                    action=action,
                    plan_run_id=plan.run_id,
                    resource_ref=resource_ref,
                )
            except PolicyViolationError as error:
                return self._reject(
                    unit_of_work=unit_of_work,
                    command=command,
                    action=action,
                    plan_run_id=plan.run_id,
                    now_ms=now_ms,
                    detail=str(error),
                    event_type="APPROVAL_SOURCE_AUTHORITY_BLOCKED",
                )

            duplicate_decision = None
            calendar_decision = None
            try:
                if action.tool_name == TASK_CREATE_TOOL:
                    duplicate_decision = require_duplicate_acknowledgement(
                        risk=action.risk,
                        acknowledged=command.duplicate_acknowledged,
                    )
                    approval_source_snapshot = merge_approval_snapshot_metadata(
                        approval_source_snapshot,
                        approval_source_snapshot_for_task_duplicate(
                            risk=action.risk,
                            acknowledged=command.duplicate_acknowledged,
                        ),
                    )

                if action.tool_name in CALENDAR_CONFLICT_TOOLS:
                    require_feasibility_approval(action.risk)
                    calendar_decision = require_calendar_conflict_acknowledgement(
                        risk=action.risk,
                        acknowledged=command.calendar_conflict_acknowledged,
                    )
                    approval_source_snapshot = merge_approval_snapshot_metadata(
                        approval_source_snapshot,
                        approval_source_snapshot_for_calendar_conflict(
                            risk=action.risk,
                            acknowledged=command.calendar_conflict_acknowledged,
                        ),
                        approval_source_snapshot_for_feasibility(risk=action.risk),
                    )
            except PolicyViolationError as error:
                return self._reject(
                    unit_of_work=unit_of_work,
                    command=command,
                    action=action,
                    plan_run_id=plan.run_id,
                    now_ms=now_ms,
                    detail=str(error),
                    event_type="APPROVAL_POLICY_BLOCKED",
                )

            approval_result = unit_of_work.actions.approve_write(
                action.id,
                expected_version=command.expected_version,
                updated_at_ms=now_ms,
            )
            if not approval_result.applied:
                response = ApproveActionResult(
                    applied=False,
                    result_code=approval_result.result_code.value,
                    action_id=action.id,
                    action_status=approval_result.current_status.value,
                    action_version=approval_result.current_version,
                    next_allowed_commands=tuple(
                        item.value for item in approval_result.next_allowed_commands
                    ),
                    conflict_detail=approval_result.conflict_detail,
                )
                self._finish_receipt(
                    unit_of_work,
                    command.command_id,
                    response,
                    approval_result.current_version,
                    now_ms,
                )
                unit_of_work.commit()
                return response

            source_snapshot_hash = calculate_canonical_json_hash(approval_source_snapshot)
            approval = ApprovalRecord(
                id=command.approval_id,
                action_id=action.id,
                approval_no=len(unit_of_work.approvals.list_by_action(action.id)) + 1,
                action_version=approval_result.current_version,
                status=ApprovalStatus.ACTIVE,
                approved_by_account_id=command.approved_by_account_id,
                approved_by_display=command.approved_by_display,
                arguments_snapshot_json=action.arguments_json,
                canonical_arguments_hash=action.arguments_hash,
                source_snapshot_json=canonicalize_json_value(approval_source_snapshot),
                source_snapshot_hash=source_snapshot_hash,
                policy_version=entry.registry_version,
                tool_schema_version=entry.input_schema_version,
                idempotency_key=command.idempotency_key,
                recovery_fingerprint=calculate_recovery_fingerprint(
                    tool_name=action.tool_name,
                    arguments_hash=action.arguments_hash,
                    source_snapshot_hash=source_snapshot_hash,
                ),
                approved_at_ms=now_ms,
                expires_at_ms=now_ms + command.ttl_ms,
                consumed_at_ms=None,
            )
            unit_of_work.approvals.insert(approval)

            if plan.status is PlanStatus.WAITING_APPROVAL:
                unit_of_work.plans.activate_waiting(plan.id)

            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="ACTION_APPROVED",
                    status=ActionStatus.APPROVED.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {
                            "approval_id": approval.id,
                            "command_id": command.command_id,
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="ACTION_APPROVED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={
                        "approval_id": approval.id,
                        "command_id": command.command_id,
                    },
                    created_at_ms=now_ms,
                )
            )

            if (
                action.tool_name == TASK_CREATE_TOOL
                and duplicate_decision is not None
                and duplicate_decision.value != "NOT_DUPLICATE"
            ):
                unit_of_work.audits.add(
                    audit_event(
                        run_id=plan.run_id,
                        action_id=action.id,
                        event_type="TASK_DUPLICATE_OVERRIDE_ACKNOWLEDGED",
                        outcome=ResultCode.TRANSITION_APPLIED.value,
                        metadata={
                            "approval_id": approval.id,
                            "decision": duplicate_decision.value,
                        },
                        created_at_ms=now_ms,
                    )
                )
            if (
                action.tool_name in CALENDAR_CONFLICT_TOOLS
                and calendar_decision is not None
                and calendar_decision is not CalendarConflictDecision.NO_CONFLICT
            ):
                unit_of_work.audits.add(
                    audit_event(
                        run_id=plan.run_id,
                        action_id=action.id,
                        event_type="CALENDAR_CONFLICT_OVERRIDE_ACKNOWLEDGED",
                        outcome=ResultCode.TRANSITION_APPLIED.value,
                        metadata={"approval_id": approval.id},
                        created_at_ms=now_ms,
                    )
                )

            response = ApproveActionResult(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                action_id=action.id,
                action_status=approval_result.current_status.value,
                action_version=approval_result.current_version,
                next_allowed_commands=tuple(
                    item.value for item in approval_result.next_allowed_commands
                ),
                approval_id=approval.id,
            )
            self._finish_receipt(
                unit_of_work,
                command.command_id,
                response,
                approval_result.current_version,
                now_ms,
            )
            unit_of_work.commit()
            return response

    def _resolve_existing_receipt(
        self,
        *,
        unit_of_work: UnitOfWork,
        receipt: CommandReceiptRecord,
        command: ApproveActionCommand,
    ) -> ApproveActionResult:
        if receipt.request_hash != command.request_hash:
            emit_command_rejected_hash_mismatch(
                unit_of_work=unit_of_work,
                receipt=receipt,
                run_id=None,
                action_id=command.action_id,
                now_ms=self._now_ms(),
            )
            action = unit_of_work.actions.get_by_id(command.action_id)
            if action is None:
                return ApproveActionResult(
                    applied=False,
                    result_code=ResultCode.DUPLICATE_COMMAND.value,
                    action_id=command.action_id,
                    action_status="UNKNOWN",
                    action_version=receipt.result_version or 0,
                    next_allowed_commands=(),
                    request_replayed=True,
                    conflict_detail=(
                        "command_id already exists with a different request_hash"
                    ),
                )
            return replace(
                self._result(
                    action=action,
                    applied=False,
                    result_code=ResultCode.DUPLICATE_COMMAND,
                    conflict_detail=(
                        "command_id already exists with a different request_hash"
                    ),
                ),
                request_replayed=True,
            )

        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            raise RuntimeError("RECEIVED receipt recovery requires aggregate-specific handling")

        payload = loads(receipt.response_json)
        if not isinstance(payload, dict):
            raise RuntimeError("approval receipt response must be an object")
        next_allowed_commands = payload.get("next_allowed_commands")
        if not isinstance(next_allowed_commands, list) or not all(
            isinstance(item, str) for item in next_allowed_commands
        ):
            raise RuntimeError("approval receipt next_allowed_commands is invalid")
        payload["next_allowed_commands"] = tuple(next_allowed_commands)
        return replace(
            ApproveActionResult(**payload),
            request_replayed=True,
        )

    def _reject(
        self,
        *,
        unit_of_work: UnitOfWork,
        command: ApproveActionCommand,
        action: ActionRecord,
        plan_run_id: str,
        now_ms: int,
        detail: str,
        event_type: str,
    ) -> ApproveActionResult:
        response = self._result(
            action=action,
            applied=False,
            result_code=ResultCode.STATE_CONFLICT,
            conflict_detail=detail,
        )
        unit_of_work.audits.add(
            audit_event(
                run_id=plan_run_id,
                action_id=action.id,
                event_type=event_type,
                outcome=ResultCode.STATE_CONFLICT.value,
                metadata={"command_id": command.command_id},
                created_at_ms=now_ms,
            )
        )
        self._finish_receipt(
            unit_of_work,
            command.command_id,
            response,
            action.version,
            now_ms,
        )
        unit_of_work.commit()
        return response

    @staticmethod
    def _result(
        *,
        action: ActionRecord,
        applied: bool,
        result_code: ResultCode,
        conflict_detail: str | None,
    ) -> ApproveActionResult:
        return ApproveActionResult(
            applied=applied,
            result_code=result_code.value,
            action_id=action.id,
            action_status=action.status,
            action_version=action.version,
            next_allowed_commands=tuple(
                item.value
                for item in next_allowed_action_commands(
                    ActionStatus(action.status),
                    effect_type=EffectType(action.effect_type),
                )
            ),
            conflict_detail=conflict_detail,
        )

    @staticmethod
    def _finish_receipt(
        unit_of_work: UnitOfWork,
        command_id: str,
        response: ApproveActionResult,
        result_version: int,
        completed_at_ms: int,
    ) -> None:
        unit_of_work.command_receipts.finish_json(
            command_id=command_id,
            applied=response.applied,
            result_code=ResultCode(response.result_code),
            result_version=result_version,
            response_json=dumps(asdict(response), sort_keys=True),
            completed_at_ms=completed_at_ms,
        )
