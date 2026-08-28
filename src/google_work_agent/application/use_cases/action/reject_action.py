"""Canonical persisted Application authority for Action rejection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from json import dumps, loads
from re import fullmatch

from google_work_agent.application.persistence_cas import update_action_record
from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetIssuer
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.application.use_cases.sse_event.project_run_event import (
    ProjectRunEventCommand,
    ProjectRunEventHandler,
)
from google_work_agent.application.write_persistence import (
    append_approval_revoked_audits,
    emit_command_rejected_hash_mismatch,
    revoke_active_approvals,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import (
    ActionStatusV1,
    EffectType,
    next_allowed_action_commands,
)
from google_work_agent.domain.action.transitions.reject_action import transition_reject_action
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import UUIDPort
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
    RunExecutionRefV1,
    WorkflowHandoffStageV1,
)


@dataclass(frozen=True, slots=True)
class RejectActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class RejectActionResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    request_replayed: bool = False
    conflict_detail: str | None = None


class RejectActionHandler:
    """Persist rejection, revoke approval authority, and block dependents."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        id_generator: UUIDPort,
        resume_target_registry: ResumeTargetIssuer,
        schedule_run_execution: Callable[
            [ScheduleRunExecutionCommand], RunExecutionAcceptedV1
        ],
        project_run_event: ProjectRunEventHandler | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._id_generator = id_generator
        self._resume_target_registry = resume_target_registry
        self._schedule_run_execution = schedule_run_execution
        self._project_run_event = project_run_event

    def __call__(self, command: RejectActionCommand) -> RejectActionResult:
        if (
            command.reason_code is not None
            and fullmatch(r"[A-Z][A-Z0-9_]{0,127}", command.reason_code) is None
        ):
            raise ValueError("reason_code must be a safe uppercase identifier")
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._resolve_existing_receipt(unit_of_work, existing, command)
            now_ms = self._now_ms()
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="RejectAction",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = self._require_action(unit_of_work, command.action_id)
            plan = unit_of_work.plans.load_bundle(action.plan_id)
            if plan is None:
                raise LookupError(f"plan not found: {action.plan_id}")
            run = unit_of_work.runs.get(plan.run_id)
            if run is None:
                raise LookupError(f"run not found: {plan.run_id}")
            current_plan = max(
                current_plan_tuple(unit_of_work.plans, plan.run_id),
                key=lambda candidate: getattr(candidate, "revision_no", 0),
                default=None,
            )
            conversation = unit_of_work.conversations.get(run.conversation_id)
            if conversation is None:
                raise LookupError(f"conversation not found: {run.conversation_id}")
            actor_account_id = conversation.account_id

            preview = transition_reject_action(
                ActionStatusV1(action.status),
                action.version,
                command.expected_version,
                effect_type=EffectType(action.effect_type),
                plan_status=plan.status,
                plan_is_current=current_plan is not None and current_plan.id == plan.id,
            )
            revoked_approval_ids: tuple[str, ...] = ()
            if preview.applied:
                revoked_approval_ids = revoke_active_approvals(unit_of_work, action.id)
                append_approval_revoked_audits(
                    unit_of_work,
                    run_id=plan.run_id,
                    action_id=action.id,
                    approval_ids=revoked_approval_ids,
                    command_id=command.command_id,
                    created_at_ms=now_ms,
                )
                if (
                    update_action_record(
                        unit_of_work,
                        action.id,
                        expected_version=action.version,
                        expected_status=ActionStatusV1(action.status),
                        next_status=preview.current_status,
                        updated_at_ms=now_ms,
                    )
                    is None
                ):
                    raise RuntimeError("validated RejectAction CAS failed")
            result = preview
            response = RejectActionResult(
                applied=result.applied,
                result_code=result.result_code.value,
                action_id=action.id,
                action_status=result.current_status.value,
                action_version=result.current_version,
                next_allowed_commands=tuple(
                    item.value
                    for item in next_allowed_action_commands(
                        result.current_status, effect_type=EffectType(action.effect_type)
                    )
                ),
                conflict_detail=result.conflict_detail,
            )
            if result.applied:
                blocked = self._block_dependents(
                    unit_of_work=unit_of_work,
                    rejected_action_id=action.id,
                    run_id=run.id,
                    command_id=command.command_id,
                    actor_account_id=actor_account_id,
                    now_ms=now_ms,
                )
                metadata: dict[str, object] = {
                    "plan_id": plan.id,
                    "action_id": action.id,
                    "command_id": command.command_id,
                    "previous_status": action.status,
                    "new_status": result.current_status.value,
                    "reason_present": command.reason_code is not None,
                    "revoked_approval_ids": list(revoked_approval_ids),
                    "blocked_dependent_action_ids": list(blocked),
                }
                if command.reason_code is not None:
                    metadata["reason_code"] = command.reason_code
                unit_of_work.traces.append(
                    TraceEventRecord(
                        run_id=run.id,
                        action_id=action.id,
                        event_type="ACTION_REJECTED",
                        status=result.current_status.value,
                        duration_ms=None,
                        payload_json=dumps({"command_id": command.command_id}, sort_keys=True),
                        created_at_ms=now_ms,
                    )
                )
                unit_of_work.audits.append(
                    self._audit_event(
                        run_id=run.id,
                        action_id=action.id,
                        actor_account_id=actor_account_id,
                        event_type="ACTION_REJECTED",
                        metadata=metadata,
                        created_at_ms=now_ms,
                    )
                )
                handoff_id = self._stage_preflight_handoff(
                    unit_of_work=unit_of_work,
                    run_id=run.id,
                    trigger_command_id=command.command_id,
                )
            else:
                handoff_id = None
            response = self._finish(unit_of_work, command, response, now_ms)
            if response.applied and self._project_run_event is not None:
                self._project_run_event(
                    ProjectRunEventCommand(
                        run_id=run.id,
                        occurred_at_ms=now_ms,
                        action_id=command.action_id,
                        event_type="action_status",
                        payload={"action_status": "REJECTED"},
                    )
                )
            if handoff_id is not None:
                self._schedule_run_execution(
                    ScheduleRunExecutionCommand(handoff_id=handoff_id)
                )
            return response

    def _stage_preflight_handoff(
        self,
        *,
        unit_of_work: UnitOfWork,
        run_id: str,
        trigger_command_id: str,
    ) -> str:
        binding = unit_of_work.checkpoints.load_workflow_binding(run_id)
        if binding is None:
            raise RuntimeError("action rejection requires a durable workflow binding")
        checkpoint = unit_of_work.checkpoints.load_same_run_checkpoint(
            run_id, binding.langgraph_thread_id
        )
        if checkpoint is None:
            raise RuntimeError("action rejection requires a durable workflow checkpoint")
        target = self._resume_target_registry.issue_main_stage(
            binding.graph_profile, "PREFLIGHT", binding.graph_version
        )
        handoff = unit_of_work.workflow_handoffs.stage_pending(
            WorkflowHandoffStageV1(
                schema_version=1,
                handoff_id=self._id_generator.new_uuid(),
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

    def _resolve_existing_receipt(
        self, unit_of_work: UnitOfWork, receipt: CommandReceiptRecord, command: RejectActionCommand
    ) -> RejectActionResult:
        if receipt.request_hash != command.request_hash:
            emit_command_rejected_hash_mismatch(
                unit_of_work=unit_of_work,
                receipt=receipt,
                run_id=None,
                action_id=command.action_id,
                now_ms=self._now_ms(),
            )
            action = unit_of_work.actions.get(command.action_id)
            if action is None:
                return RejectActionResult(
                    False,
                    ResultCode.DUPLICATE_COMMAND.value,
                    command.action_id,
                    "UNKNOWN",
                    receipt.result_version or 0,
                    (),
                    True,
                    "command_id already exists with a different request_hash",
                )
            return replace(
                self._result(
                    action,
                    ResultCode.DUPLICATE_COMMAND,
                    "command_id already exists with a different request_hash",
                ),
                request_replayed=True,
            )
        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            raise RuntimeError("RECEIVED receipt recovery requires aggregate-specific handling")
        payload = loads(receipt.response_json)
        if not isinstance(payload, dict):
            raise RuntimeError("reject receipt response must be an object")
        payload.setdefault("request_replayed", False)
        payload["next_allowed_commands"] = tuple(payload["next_allowed_commands"])
        return replace(RejectActionResult(**payload), request_replayed=True)

    @staticmethod
    def _finish(
        unit_of_work: UnitOfWork,
        command: RejectActionCommand,
        response: RejectActionResult,
        now_ms: int,
    ) -> RejectActionResult:
        unit_of_work.command_receipts.store_result(
            command_id=command.command_id,
            applied=response.applied,
            result_code=ResultCode(response.result_code),
            result_version=response.action_version,
            response_json=dumps(asdict(response), sort_keys=True),
            completed_at_ms=now_ms,
        )
        unit_of_work.commit()
        return response

    @staticmethod
    def _result(
        action: ActionRecord, result_code: ResultCode, conflict_detail: str | None
    ) -> RejectActionResult:
        return RejectActionResult(
            False,
            result_code.value,
            action.id,
            action.status,
            action.version,
            tuple(
                item.value
                for item in next_allowed_action_commands(
                    ActionStatusV1(action.status), effect_type=EffectType(action.effect_type)
                )
            ),
            conflict_detail=conflict_detail,
        )

    @staticmethod
    def _audit_event(
        *,
        run_id: str,
        action_id: str,
        actor_account_id: str,
        event_type: str,
        metadata: dict[str, object],
        created_at_ms: int,
    ) -> AuditEventRecord:
        return AuditEventRecord(
            account_id=actor_account_id,
            run_id=run_id,
            action_id=action_id,
            actor_type="USER",
            actor_id=actor_account_id,
            actor_display=None,
            event_type=event_type,
            outcome=ResultCode.TRANSITION_APPLIED.value,
            metadata_json=dumps(metadata, sort_keys=True),
            created_at_ms=created_at_ms,
        )

    @classmethod
    def _block_dependents(
        cls,
        *,
        unit_of_work: UnitOfWork,
        rejected_action_id: str,
        run_id: str,
        command_id: str,
        actor_account_id: str,
        now_ms: int,
    ) -> tuple[str, ...]:
        blocked: list[str] = []
        pending = list(unit_of_work.actions.list_dependents(rejected_action_id))
        visited: set[str] = set()
        while pending:
            dependent_id = pending.pop(0)
            if dependent_id in visited:
                continue
            visited.add(dependent_id)
            dependent = unit_of_work.actions.get(dependent_id)
            if dependent is None or dependent.status not in {
                ActionStatusV1.PROPOSED.value,
                ActionStatusV1.MODIFIED.value,
                ActionStatusV1.APPROVED.value,
            }:
                continue
            revoked = revoke_active_approvals(unit_of_work, dependent_id)
            append_approval_revoked_audits(
                unit_of_work,
                run_id=run_id,
                action_id=dependent_id,
                approval_ids=revoked,
                command_id=command_id,
                created_at_ms=now_ms,
            )
            if (
                update_action_record(
                    unit_of_work,
                    dependent_id,
                    expected_version=dependent.version,
                    expected_status=ActionStatusV1(dependent.status),
                    next_status=ActionStatusV1.DEPENDENCY_BLOCKED,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError(f"dependency block transition failed: {dependent_id}")
            blocked.append(dependent_id)
            metadata: dict[str, object] = {
                "command_id": command_id,
                "blocked_by_action_id": rejected_action_id,
                "previous_status": dependent.status,
                "new_status": ActionStatusV1.DEPENDENCY_BLOCKED.value,
                "revoked_approval_ids": list(revoked),
            }
            unit_of_work.traces.append(
                TraceEventRecord(
                    run_id=run_id,
                    action_id=dependent_id,
                    event_type="ACTION_DEPENDENCY_BLOCKED",
                    status=ActionStatusV1.DEPENDENCY_BLOCKED.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"command_id": command_id, "blocked_by_action_id": rejected_action_id},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.append(
                cls._audit_event(
                    run_id=run_id,
                    action_id=dependent_id,
                    actor_account_id=actor_account_id,
                    event_type="ACTION_DEPENDENCY_BLOCKED",
                    metadata=metadata,
                    created_at_ms=now_ms,
                )
            )
            pending.extend(unit_of_work.actions.list_dependents(dependent_id))
        return tuple(blocked)

    @staticmethod
    def _require_action(unit_of_work: UnitOfWork, action_id: str) -> ActionRecord:
        action = unit_of_work.actions.get(action_id)
        if action is None:
            raise LookupError(f"action not found: {action_id}")
        return action
