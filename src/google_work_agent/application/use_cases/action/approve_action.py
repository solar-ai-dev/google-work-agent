"""Canonical persisted Application authority for explicit Action approval."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from json import dumps

from google_work_agent.application.policy_kernels.calendar_conflict import CalendarConflictDecision
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.action.approval_source_snapshot import (
    build_approval_source_snapshot,
)
from google_work_agent.application.use_cases.action.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
    approval_source_snapshot_for_calendar_conflict,
    calendar_conflict_authority,
    require_calendar_conflict_acknowledgement,
)
from google_work_agent.application.use_cases.action.feasibility import (
    approval_source_snapshot_for_feasibility,
    feasibility_authority,
    require_feasibility_approval,
)
from google_work_agent.application.use_cases.action.persistence_cas import update_action_record
from google_work_agent.application.use_cases.action.task_duplicates import (
    TASK_CREATE_TOOL,
    approval_source_snapshot_for_task_duplicate,
    duplicate_authority,
    require_duplicate_acknowledgement,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    action_response_from_result,
    audit_event,
    finish_json_receipt,
    require_action,
    require_plan,
    resolve_existing_action_receipt,
)
from google_work_agent.application.use_cases.claim.write_execution_integrity import (
    calculate_recovery_fingerprint,
)
from google_work_agent.application.use_cases.execution_attempt.write_execution_contracts import (
    WriteActionResponse,
)
from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetIssuer
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import (
    ActionStatusV1,
    EffectType,
    PolicyViolationError,
    next_allowed_action_commands,
)
from google_work_agent.domain.action.transitions.approve_action import transition_approve_action
from google_work_agent.domain.approval.model import Approval as ApprovalRecord
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.canonical import (
    calculate_canonical_json_hash,
    canonicalize_json_value,
)
from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.persistence.approval_repository import active_approval_tuple
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
    RunExecutionRefV1,
    WorkflowHandoffStageV1,
)
from google_work_agent.ports.system.uuid_port import UUIDPort


@dataclass(frozen=True, slots=True)
class ApproveActionCommand:
    command_id: str
    request_hash: str
    request_id: str
    action_id: str
    expected_version: int
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
    conflict_detail: str | None = None


class ApproveActionHandler:
    """Own durable approval semantics and server-side approval source authority."""

    def __init__(
        self,
        *,
        get_approval_ttl_minutes: Callable[[], int],
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        id_generator: UUIDPort,
        resume_target_registry: ResumeTargetIssuer,
        schedule_run_execution: Callable[[ScheduleRunExecutionCommand], RunExecutionAcceptedV1],
    ) -> None:
        self._get_approval_ttl_minutes = get_approval_ttl_minutes
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._id_generator = id_generator
        self._resume_target_registry = resume_target_registry
        self._schedule_run_execution = schedule_run_execution
        self._registry = load_signed_tool_registry()

    def __call__(self, command: ApproveActionCommand) -> ApproveActionResult:
        ttl_ms = self._get_approval_ttl_minutes() * 60_000
        if ttl_ms <= 0:
            raise RuntimeError("approval_ttl_minutes must be positive")

        run_id: str | None = None
        handoff_id: str | None = None
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                replay = resolve_existing_action_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                    now_ms=self._now_ms(),
                )
                result = self._result_from_response(replay)
                if result.applied:
                    action = require_action(unit_of_work, command.action_id)
                    plan = require_plan(unit_of_work, action.plan_id)
                    run_id = plan.run_id
                    replay_handoff = unit_of_work.workflow_handoffs.get_by_trigger_command_id(
                        command.command_id
                    )
                    handoff_id = None if replay_handoff is None else replay_handoff.handoff_id
                else:
                    return result
            else:
                now_ms = self._now_ms()
                unit_of_work.command_receipts.reserve_or_replay(
                    command_id=command.command_id,
                    command_type="ApproveAction",
                    request_hash=command.request_hash,
                    aggregate_type="Action",
                    aggregate_id=command.action_id,
                    created_at_ms=now_ms,
                )
                action = require_action(unit_of_work, command.action_id)
                plan = require_plan(unit_of_work, action.plan_id)
                run = unit_of_work.runs.get(plan.run_id)
                if run is None:
                    raise LookupError(f"run not found: {plan.run_id}")
                conversation = unit_of_work.conversations.get(run.conversation_id)
                if conversation is None:
                    raise LookupError(f"conversation not found: {run.conversation_id}")
                entry = self._registry.get_required(action.connector_id, action.tool_name)

                plans = tuple(current_plan_tuple(unit_of_work.plans, run.id))
                current_plan = max(
                    plans,
                    key=lambda candidate: getattr(candidate, "revision_no", 0),
                    default=None,
                )
                if (
                    plan.status is not PlanStatusV1.WAITING_APPROVAL
                    or current_plan is None
                    or current_plan.id != plan.id
                    or getattr(run, "status", RunStatusV1.WAITING_APPROVAL)
                    not in {RunStatusV1.WAITING_APPROVAL, RunStatusV1.VERIFYING}
                ):
                    result = ApproveActionResult(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=(),
                        conflict_detail=(
                            "superseded Plan children are history-only"
                            if plan.status is PlanStatusV1.SUPERSEDED
                            else "approval requires the current published Plan and parent Run"
                        ),
                    )
                    finish_json_receipt(
                        unit_of_work,
                        command.command_id,
                        result,
                        action.version,
                        now_ms,
                    )
                    unit_of_work.commit()
                    return result

                if plan.review_status is not PlanReviewStatus.PASSED:
                    result = ApproveActionResult(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=(),
                        conflict_detail=(
                            "plan review must pass after the latest action modification"
                        ),
                    )
                    unit_of_work.audits.append(
                        audit_event(
                            run_id=plan.run_id,
                            action_id=action.id,
                            event_type="PLAN_REVIEW_APPROVAL_BLOCKED",
                            outcome=ResultCode.STATE_CONFLICT.value,
                            metadata={
                                "command_id": command.command_id,
                                "review_status": plan.review_status.value,
                                "review_version": plan.review_version,
                            },
                            created_at_ms=now_ms,
                        )
                    )
                    finish_json_receipt(
                        unit_of_work,
                        command.command_id,
                        result,
                        action.version,
                        now_ms,
                    )
                    unit_of_work.commit()
                    return result

                resource_ref = (
                    None
                    if action.target_resource_ref_id is None
                    else unit_of_work.resource_refs.get(action.target_resource_ref_id)
                )
                source_snapshot = build_approval_source_snapshot(
                    action=action,
                    plan_run_id=plan.run_id,
                    resource_ref=resource_ref,
                )
                duplicate_decision = None
                calendar_decision = None

                if (
                    action.tool_name == TASK_CREATE_TOOL
                    and action.version == command.expected_version
                ):
                    try:
                        duplicate_decision = require_duplicate_acknowledgement(
                            risk=action.risk,
                            acknowledged=command.duplicate_acknowledged,
                        )
                    except PolicyViolationError as error:
                        result = self._blocked_result(action, str(error))
                        unit_of_work.audits.append(
                            audit_event(
                                run_id=plan.run_id,
                                action_id=action.id,
                                event_type="TASK_DUPLICATE_APPROVAL_BLOCKED",
                                outcome=ResultCode.STATE_CONFLICT.value,
                                metadata={
                                    "command_id": command.command_id,
                                    "decision": (
                                        duplicate_authority(action.risk) or ("UNKNOWN", ())
                                    )[0],
                                },
                                created_at_ms=now_ms,
                            )
                        )
                        finish_json_receipt(
                            unit_of_work, command.command_id, result, action.version, now_ms
                        )
                        unit_of_work.commit()
                        return result
                    source_snapshot = {
                        **source_snapshot,
                        **approval_source_snapshot_for_task_duplicate(
                            risk=action.risk,
                            acknowledged=command.duplicate_acknowledged,
                        ),
                    }

                if (
                    action.tool_name in CALENDAR_CONFLICT_TOOLS
                    and action.version == command.expected_version
                ):
                    try:
                        require_feasibility_approval(action.risk)
                    except PolicyViolationError as error:
                        result = self._blocked_result(action, str(error))
                        unit_of_work.audits.append(
                            audit_event(
                                run_id=plan.run_id,
                                action_id=action.id,
                                event_type="FEASIBILITY_APPROVAL_BLOCKED",
                                outcome=ResultCode.STATE_CONFLICT.value,
                                metadata={
                                    "command_id": command.command_id,
                                    **self._feasibility_audit_metadata(action.risk),
                                },
                                created_at_ms=now_ms,
                            )
                        )
                        finish_json_receipt(
                            unit_of_work, command.command_id, result, action.version, now_ms
                        )
                        unit_of_work.commit()
                        return result
                    try:
                        calendar_decision = require_calendar_conflict_acknowledgement(
                            risk=action.risk,
                            acknowledged=command.calendar_conflict_acknowledged,
                        )
                    except PolicyViolationError as error:
                        result = self._blocked_result(action, str(error))
                        unit_of_work.audits.append(
                            audit_event(
                                run_id=plan.run_id,
                                action_id=action.id,
                                event_type="CALENDAR_CONFLICT_APPROVAL_BLOCKED",
                                outcome=ResultCode.STATE_CONFLICT.value,
                                metadata={
                                    "command_id": command.command_id,
                                    **self._calendar_conflict_audit_metadata(
                                        risk=action.risk, action_id=action.id
                                    ),
                                },
                                created_at_ms=now_ms,
                            )
                        )
                        finish_json_receipt(
                            unit_of_work, command.command_id, result, action.version, now_ms
                        )
                        unit_of_work.commit()
                        return result
                    source_snapshot = {
                        **source_snapshot,
                        **approval_source_snapshot_for_calendar_conflict(
                            risk=action.risk,
                            acknowledged=command.calendar_conflict_acknowledged,
                        ),
                        **approval_source_snapshot_for_feasibility(risk=action.risk),
                    }

                approval_result = transition_approve_action(
                    ActionStatusV1(action.status),
                    action.version,
                    command.expected_version,
                    effect_type=EffectType(action.effect_type),
                    plan_review_passed=plan.review_status is PlanReviewStatus.PASSED,
                    plan_status=plan.status,
                    plan_is_current=current_plan is not None and current_plan.id == plan.id,
                    run_status=RunStatusV1(run.status),
                )
                if not approval_result.applied:
                    response = action_response_from_result(
                        action_id=action.id,
                        result=approval_result,
                    )
                    result = self._result_from_response(response)
                    finish_json_receipt(
                        unit_of_work,
                        command.command_id,
                        result,
                        action.version,
                        now_ms,
                    )
                    unit_of_work.commit()
                    return result
                if (
                    update_action_record(
                        unit_of_work,
                        action.id,
                        expected_version=action.version,
                        expected_status=ActionStatusV1(action.status),
                        next_status=approval_result.current_status,
                        updated_at_ms=now_ms,
                    )
                    is None
                ):
                    raise RuntimeError("validated ApproveAction CAS failed")

                source_snapshot_hash = calculate_canonical_json_hash(source_snapshot)
                approval = ApprovalRecord(
                    id=self._id_generator.new_uuid(),
                    action_id=action.id,
                    approval_no=len(active_approval_tuple(unit_of_work.approvals, action.id)) + 1,
                    action_version=approval_result.current_version,
                    status=ApprovalStatusV1.ACTIVE,
                    approved_by_account_id=conversation.account_id,
                    approved_by_display=None,
                    arguments_snapshot_json=action.arguments_json,
                    canonical_arguments_hash=action.arguments_hash,
                    source_snapshot_json=canonicalize_json_value(source_snapshot),
                    source_snapshot_hash=source_snapshot_hash,
                    policy_version=entry.registry_version,
                    tool_schema_version=entry.input_schema_version,
                    idempotency_key=calculate_canonical_json_hash(
                        {
                            "operation": "ApproveActionIdempotencyKeyV1",
                            "payload": {
                                "action_id": action.id,
                                "command_id": command.command_id,
                            },
                        }
                    ),
                    recovery_fingerprint=calculate_recovery_fingerprint(
                        tool_name=action.tool_name,
                        arguments_hash=action.arguments_hash,
                        source_snapshot_hash=source_snapshot_hash,
                    ),
                    approved_at_ms=now_ms,
                    expires_at_ms=now_ms + ttl_ms,
                    consumed_at_ms=None,
                )
                unit_of_work.approvals.insert_active_snapshot(approval)

                # Write Plans remain WAITING_APPROVAL while approved Actions execute.

                unit_of_work.traces.append(
                    TraceEventRecord(
                        run_id=plan.run_id,
                        action_id=action.id,
                        event_type="WRITE_ACTION_APPROVED",
                        status=ActionStatusV1.APPROVED.value,
                        duration_ms=None,
                        payload_json=dumps(
                            {"approval_id": approval.id, "command_id": command.command_id},
                            sort_keys=True,
                        ),
                        created_at_ms=now_ms,
                    )
                )
                unit_of_work.audits.append(
                    audit_event(
                        run_id=plan.run_id,
                        action_id=action.id,
                        event_type="ACTION_APPROVED",
                        outcome=ResultCode.TRANSITION_APPLIED.value,
                        metadata={"approval_id": approval.id, "command_id": command.command_id},
                        created_at_ms=now_ms,
                    )
                )
                if (
                    action.tool_name == TASK_CREATE_TOOL
                    and duplicate_decision is not None
                    and duplicate_decision.value != "NOT_DUPLICATE"
                ):
                    unit_of_work.audits.append(
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
                    unit_of_work.audits.append(
                        audit_event(
                            run_id=plan.run_id,
                            action_id=action.id,
                            event_type="CALENDAR_CONFLICT_OVERRIDE_ACKNOWLEDGED",
                            outcome=ResultCode.TRANSITION_APPLIED.value,
                            metadata={
                                "approval_id": approval.id,
                                **self._calendar_conflict_audit_metadata(
                                    risk=action.risk, action_id=action.id
                                ),
                            },
                            created_at_ms=now_ms,
                        )
                    )

                result = ApproveActionResult(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED.value,
                    action_id=action.id,
                    action_status=approval_result.current_status.value,
                    action_version=approval_result.current_version,
                    next_allowed_commands=tuple(
                        item.value for item in approval_result.next_allowed_commands
                    ),
                )
                handoff_id = self._stage_preflight_handoff(
                    unit_of_work=unit_of_work,
                    run_id=plan.run_id,
                    trigger_command_id=command.command_id,
                )
                finish_json_receipt(
                    unit_of_work,
                    command.command_id,
                    result,
                    approval_result.current_version,
                    now_ms,
                )
                unit_of_work.commit()
                run_id = plan.run_id

        if run_id is not None and handoff_id is not None:
            self._schedule_run_execution(ScheduleRunExecutionCommand(handoff_id=handoff_id))
        return result

    def _stage_preflight_handoff(
        self,
        *,
        unit_of_work: UnitOfWork,
        run_id: str,
        trigger_command_id: str,
    ) -> str:
        binding = unit_of_work.checkpoints.load_workflow_binding(run_id)
        if binding is None:
            raise RuntimeError("approval requires a durable workflow binding")
        checkpoint = unit_of_work.checkpoints.load_same_run_checkpoint(
            run_id, binding.langgraph_thread_id
        )
        if checkpoint is None:
            raise RuntimeError("approval requires a durable workflow checkpoint")
        target = self._resume_target_registry.issue_main_stage(
            binding.graph_profile, "PREFLIGHT", binding.graph_version
        )
        handoff_id = self._id_generator.new_uuid()
        handoff = unit_of_work.workflow_handoffs.stage_pending(
            WorkflowHandoffStageV1(
                schema_version=1,
                handoff_id=handoff_id,
                trigger_command_id=trigger_command_id,
                execution=RunExecutionRefV1(
                    schema_version=1,
                    execution_kind="RESUME",
                    run_id=run_id,
                    langgraph_thread_id=binding.langgraph_thread_id,
                    graph_profile=binding.graph_profile,
                    graph_version=binding.graph_version,
                    requested_mode=binding.requested_mode,
                    resume_target=target,
                ),
                checkpoint_id=checkpoint.checkpoint_id,
                checkpoint_generation=checkpoint.checkpoint_generation,
                control_kind="NONE",
                control=None,
                control_payload_hash=None,
            )
        )
        return handoff.handoff_id

    @staticmethod
    def _result_from_response(response: WriteActionResponse) -> ApproveActionResult:
        return ApproveActionResult(
            applied=bool(response.applied),
            result_code=str(response.result_code),
            action_id=str(response.action_id),
            action_status=str(response.action_status),
            action_version=int(response.action_version),
            next_allowed_commands=tuple(response.next_allowed_commands),
            conflict_detail=getattr(response, "conflict_detail", None),
        )

    @staticmethod
    def _blocked_result(action: ActionRecord, detail: str) -> ApproveActionResult:
        effect_type = EffectType(action.effect_type)
        status = ActionStatusV1(action.status)
        return ApproveActionResult(
            applied=False,
            result_code=ResultCode.STATE_CONFLICT.value,
            action_id=str(action.id),
            action_status=status.value,
            action_version=int(action.version),
            next_allowed_commands=tuple(
                item.value for item in next_allowed_action_commands(status, effect_type=effect_type)
            ),
            conflict_detail=detail,
        )

    @staticmethod
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

    @staticmethod
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
