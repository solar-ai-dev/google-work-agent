"""Application use case for explicit Run recovery resolution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from json import dumps, loads

from google_work_agent.application.use_cases.action.persistence_cas import (
    update_action_record,
    update_plan_record,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    cancel_pending_actions,
    revoke_active_approvals,
)
from google_work_agent.application.use_cases.recovery.require_recovery import (
    current_recheck_input_hash,
)
from google_work_agent.application.use_cases.run.build_terminal_message import (
    BuildTerminalMessageHandler,
    BuildTerminalMessageQueryV1,
)
from google_work_agent.application.use_cases.run.cancel_intent import has_durable_cancel_intent
from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetIssuer
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.message.model import Message as MessageRecord
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.recovery.model import RecoveryResolution
from google_work_agent.domain.recovery.transitions.resolve_recovery import (
    transition_resolve_recovery,
)
from google_work_agent.domain.results import CommandResult, ResultCode
from google_work_agent.domain.run.model import RunStatusV1, next_allowed_run_commands
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.recovery_repository import RecoveryContextV1
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import (
    MainResumeStageIdV1,
    RunExecutionRefV1,
    WorkflowHandoffStageV1,
)


@dataclass(frozen=True, slots=True)
class ResolveRecoveryCommandV1:
    run_id: str
    expected_version: int
    command_id: str
    request_hash: str
    resolution: RecoveryResolution


@dataclass(frozen=True, slots=True)
class ResolveRecoveryResult:
    applied: bool
    result_code: str
    current_status: str
    current_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None
    result_kind: str | None = None
    plan_id: str | None = None
    handoff_id: str | None = None


class ResolveRecoveryHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        next_id: Callable[[], str] | None = None,
        resume_target_registry: ResumeTargetIssuer | None = None,
        schedule_run_execution: Callable[[ScheduleRunExecutionCommand], object] | None = None,
        build_terminal_message: BuildTerminalMessageHandler | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._next_id = next_id
        self._resume_target_registry = resume_target_registry
        self._schedule_run_execution = schedule_run_execution
        self._build_terminal_message = build_terminal_message or BuildTerminalMessageHandler()

    def __call__(self, command: ResolveRecoveryCommandV1) -> ResolveRecoveryResult:
        handoff_id: str | None = None
        with self._unit_of_work_factory() as unit_of_work:
            now_ms = self._now_ms()
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._replay_or_reject_duplicate(unit_of_work, command, existing)
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="ResolveRecovery",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            run = unit_of_work.runs.get(command.run_id)
            if run is None:
                raise LookupError(f"run not found: {command.run_id}")
            context = unit_of_work.recovery_contexts.load_current_context(command.run_id)
            if context is None:
                raise RuntimeError("ResolveRecovery requires a durable RecoveryContextV1")
            if run.version != command.expected_version:
                result = ResolveRecoveryResult(
                    False,
                    ResultCode.VERSION_CONFLICT.value,
                    run.status.value,
                    run.version,
                    tuple(item.value for item in next_allowed_run_commands(run.status)),
                    "expected_version does not match current_version",
                )
                self._finish_result(unit_of_work, command, result, now_ms)
                unit_of_work.commit()
                return result

            recovered_action_status = self._recovered_action_status(unit_of_work, context)
            unresolved_external_effect_count = self._unresolved_external_effect_count(
                unit_of_work, command.run_id
            )
            cancel_intent_active = has_durable_cancel_intent(
                unit_of_work.cancel_intents, command.run_id
            )
            recheck_input_hash = current_recheck_input_hash(unit_of_work, context)
            recheck_input_changed = recheck_input_hash != context.get("last_recheck_input_hash")
            decision = transition_resolve_recovery(
                run.status,
                resolution=command.resolution,
                reason=context["reason"],
                pre_recovery_status=RunStatusV1(context["pre_recovery_status"]),
                recheck_input_changed=recheck_input_changed,
                recovered_action_status=recovered_action_status,
                validated_resume_status=self._validated_resume_status(
                    unit_of_work, context, recheck_input_changed
                ),
                cancel_intent_active=cancel_intent_active,
                unresolved_external_effect_count=unresolved_external_effect_count,
                irrecoverable_confirmed=(
                    context["reason"] != "UNKNOWN_RESULT" and unresolved_external_effect_count == 0
                ),
            )
            if not decision.applied:
                if command.resolution is RecoveryResolution.RECHECK and recheck_input_changed:
                    unit_of_work.recovery_contexts.store_context(
                        {
                            **context,
                            "last_recheck_input_hash": recheck_input_hash,
                            "version": int(context["version"]) + 1,
                            "updated_at_ms": now_ms,
                        }
                    )
                result = ResolveRecoveryResult(
                    applied=False,
                    result_code=decision.result_code.value,
                    current_status=run.status.value,
                    current_version=run.version,
                    next_allowed_commands=(),
                    conflict_detail=decision.conflict_detail,
                )
                self._finish_result(unit_of_work, command, result, now_ms)
                unit_of_work.commit()
                return result

            target = decision.current_status
            plan, result_kind = self._apply_resolution_effects(
                unit_of_work,
                command=command,
                context=context,
                now_ms=now_ms,
            )
            values: dict[str, object] = {"status": target.value, "version": run.version + 1}
            if target in {RunStatusV1.COMPLETED, RunStatusV1.CANCELLED, RunStatusV1.FAILED}:
                values["finished_at_ms"] = now_ms
                values["terminal_result_kind"] = result_kind
            if not unit_of_work.runs.update_if_version_and_status(
                run.id, run.version, frozenset({run.status}), values
            ):
                raise RuntimeError("validated ResolveRecovery Run CAS failed")
            persisted = CommandResult(
                True,
                ResultCode.TRANSITION_APPLIED,
                target,
                run.version + 1,
                next_allowed_run_commands(target),
            )
            unit_of_work.recovery_contexts.clear_context(command.run_id, int(context["version"]))
            if target in {RunStatusV1.COMPLETED, RunStatusV1.CANCELLED, RunStatusV1.FAILED}:
                self._append_terminal_message(
                    unit_of_work, run.conversation_id, command.run_id, result_kind, now_ms
                )
                unit_of_work.workflow_handoffs.supersede_unconsumed_for_run(
                    command.run_id, "RECOVERY_TERMINAL"
                )
            else:
                handoff_id = self._stage_continuation(
                    unit_of_work,
                    command=command,
                    context=context,
                    target_status=target,
                    now_ms=now_ms,
                )
            result = ResolveRecoveryResult(
                applied=persisted.applied,
                result_code=persisted.result_code.value,
                current_status=persisted.current_status.value,
                current_version=persisted.current_version,
                next_allowed_commands=tuple(item.value for item in persisted.next_allowed_commands),
                conflict_detail=persisted.conflict_detail,
                result_kind=result_kind,
                plan_id=None if plan is None else plan.id,
                handoff_id=handoff_id,
            )
            metadata = dumps(
                {
                    "command_id": command.command_id,
                    "reason": context["reason"],
                    "resolution": command.resolution.value,
                },
                sort_keys=True,
            )
            unit_of_work.traces.append(
                TraceEventRecord(
                    run_id=command.run_id,
                    action_id=None
                    if context.get("action_id") is None
                    else str(context["action_id"]),
                    event_type="RECOVERY_RESOLVED",
                    status=result.current_status,
                    duration_ms=None,
                    payload_json=metadata,
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.append(
                AuditEventRecord(
                    account_id=None,
                    run_id=command.run_id,
                    action_id=None
                    if context.get("action_id") is None
                    else str(context["action_id"]),
                    actor_type="SYSTEM",
                    actor_id="run_lifecycle",
                    actor_display="Run lifecycle",
                    event_type="RECOVERY_RESOLVED",
                    outcome=result.result_code,
                    metadata_json=metadata,
                    created_at_ms=now_ms,
                )
            )
            self._append_resolution_audit(
                unit_of_work,
                command=command,
                context=context,
                result=result,
                metadata=metadata,
                now_ms=now_ms,
            )
            self._finish_result(unit_of_work, command, result, now_ms)
            unit_of_work.commit()
        if handoff_id is not None and self._schedule_run_execution is not None:
            self._schedule_run_execution(ScheduleRunExecutionCommand(handoff_id=handoff_id))
        return result

    @staticmethod
    def _recovered_action_status(
        unit_of_work: UnitOfWork,
        context: RecoveryContextV1,
    ) -> ActionStatusV1 | None:
        action_id = context.get("action_id")
        if action_id is None:
            return None
        action = unit_of_work.actions.get(str(action_id))
        return None if action is None else ActionStatusV1(action.status)

    def _validated_resume_status(
        self,
        unit_of_work: UnitOfWork,
        context: RecoveryContextV1,
        recheck_input_changed: bool,
    ) -> RunStatusV1 | None:
        if not recheck_input_changed or context["reason"] not in {
            "CHECKPOINT_MISMATCH",
            "CONTRACT_VIOLATION",
        }:
            return None
        target = context.get("registered_resume_target")
        if target is None:
            return (
                RunStatusV1(context["pre_recovery_status"])
                if context["reason"] == "CONTRACT_VIOLATION"
                else None
            )
        if self._resume_target_registry is None:
            return None
        try:
            self._resume_target_registry.validate(target)
        except ValueError:
            return None
        binding = unit_of_work.checkpoints.load_workflow_binding(context["run_id"])
        checkpoint = (
            None
            if binding is None
            else unit_of_work.checkpoints.load_same_run_checkpoint(
                context["run_id"], binding.langgraph_thread_id
            )
        )
        if checkpoint is None or checkpoint.registered_resume_target != target:
            return None
        return RunStatusV1(context["pre_recovery_status"])

    def _apply_resolution_effects(
        self,
        unit_of_work: UnitOfWork,
        *,
        command: ResolveRecoveryCommandV1,
        context: RecoveryContextV1,
        now_ms: int,
    ) -> tuple[PlanRecord | None, str | None]:
        """Preserve mismatch recovery effects at the canonical writer boundary."""
        plans = current_plan_tuple(unit_of_work.plans, command.run_id)
        plan = max(plans, key=lambda item: (item.revision_no, item.created_at_ms), default=None)
        if command.resolution is RecoveryResolution.CANCEL:
            actions = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)
            external_mutation_observed = any(
                action.status
                in {
                    ActionStatusV1.EXECUTED.value,
                    ActionStatusV1.VERIFIED.value,
                    ActionStatusV1.MISMATCH.value,
                }
                for action in actions
            )
            self._settle_terminal_children(unit_of_work, command.run_id, plan, now_ms)
            return plan, "PARTIAL" if external_mutation_observed else "CANCELLED"
        if command.resolution is RecoveryResolution.FAIL:
            self._settle_terminal_children(
                unit_of_work,
                command.run_id,
                plan,
                now_ms,
                pending_status=ActionStatusV1.BLOCKED,
            )
            return plan, "FAILED"
        if command.resolution not in {
            RecoveryResolution.ACCEPT_PARTIAL,
            RecoveryResolution.CREATE_CORRECTIVE_PLAN,
        }:
            return plan, None
        if plan is None:
            raise LookupError(f"plan not found for recovery run: {command.run_id}")
        action_id = context.get("action_id")
        action = None if action_id is None else unit_of_work.actions.get(str(action_id))
        if (
            action is None
            or action.plan_id != plan.id
            or action.status != ActionStatusV1.MISMATCH.value
        ):
            raise RuntimeError("mismatch recovery requires the current MISMATCH action")
        if has_durable_cancel_intent(unit_of_work.cancel_intents, command.run_id):
            raise RuntimeError("mismatch recovery is forbidden while cancel intent is active")
        if command.resolution is RecoveryResolution.ACCEPT_PARTIAL:
            cancel_pending_actions(
                unit_of_work=unit_of_work,
                run_id=command.run_id,
                plan_id=plan.id,
                updated_at_ms=now_ms,
            )
            if (
                update_plan_record(
                    unit_of_work,
                    plan.id,
                    expected_status=plan.status,
                    next_status=PlanStatusV1.COMPLETED,
                )
                is None
            ):
                raise RuntimeError(f"validated Plan completion CAS failed: {plan.id}")
            return plan, "PARTIAL"

        for candidate in unit_of_work.actions.list_for_plan(plan.id):
            revoke_active_approvals(unit_of_work, candidate.id)
        if (
            update_plan_record(
                unit_of_work,
                plan.id,
                expected_status=plan.status,
                next_status=PlanStatusV1.SUPERSEDED,
            )
            is None
        ):
            raise RuntimeError(f"validated Plan supersession CAS failed: {plan.id}")
        if self._next_id is None:
            raise RuntimeError("CREATE_CORRECTIVE_PLAN requires an id generator")
        corrective = PlanRecord(
            id=self._next_id(),
            run_id=command.run_id,
            revision_no=max(item.revision_no for item in plans) + 1,
            status=PlanStatusV1.DRAFT,
            summary_text=f"Corrective plan for mismatch action {action.id}",
            created_at_ms=now_ms,
        )
        unit_of_work.plans.insert_revision(corrective)
        return corrective, "CORRECTIVE_PLAN_REQUIRED"

    @staticmethod
    def _unresolved_external_effect_count(unit_of_work: UnitOfWork, run_id: str) -> int:
        return sum(
            action.status
            in {
                ActionStatusV1.EXECUTING.value,
                ActionStatusV1.UNKNOWN_RESULT.value,
                ActionStatusV1.EXECUTED.value,
            }
            for plan in current_plan_tuple(unit_of_work.plans, run_id)
            for action in unit_of_work.actions.list_for_plan(plan.id)
        )

    @staticmethod
    def _settle_terminal_children(
        unit_of_work: UnitOfWork,
        run_id: str,
        plan: PlanRecord | None,
        now_ms: int,
        pending_status: ActionStatusV1 = ActionStatusV1.CANCELLED,
    ) -> None:
        if plan is None:
            return
        if pending_status is ActionStatusV1.CANCELLED:
            cancel_pending_actions(
                unit_of_work=unit_of_work,
                run_id=run_id,
                plan_id=plan.id,
                updated_at_ms=now_ms,
            )
        else:
            pending = {
                ActionStatusV1.PROPOSED,
                ActionStatusV1.MODIFIED,
                ActionStatusV1.APPROVED,
                ActionStatusV1.EXPIRED,
            }
            for action in unit_of_work.actions.list_for_plan(plan.id):
                if ActionStatusV1(action.status) not in pending:
                    continue
                if (
                    update_action_record(
                        unit_of_work,
                        action.id,
                        expected_version=action.version,
                        expected_status=ActionStatusV1(action.status),
                        next_status=ActionStatusV1.BLOCKED,
                        updated_at_ms=now_ms,
                    )
                    is None
                ):
                    raise RuntimeError(
                        f"terminal Recovery could not block pending action {action.id}"
                    )
        for action in unit_of_work.actions.list_for_plan(plan.id):
            revoke_active_approvals(unit_of_work, action.id)
        if plan.status not in {
            PlanStatusV1.CANCELLED,
            PlanStatusV1.COMPLETED,
        } and (
            update_plan_record(
                unit_of_work,
                plan.id,
                expected_status=plan.status,
                next_status=PlanStatusV1.CANCELLED,
            )
            is None
        ):
            raise RuntimeError(f"validated terminal Plan settlement CAS failed: {plan.id}")

    @staticmethod
    def _append_resolution_audit(
        unit_of_work: UnitOfWork,
        *,
        command: ResolveRecoveryCommandV1,
        context: RecoveryContextV1,
        result: ResolveRecoveryResult,
        metadata: str,
        now_ms: int,
    ) -> None:
        event_by_resolution = {
            RecoveryResolution.ACCEPT_PARTIAL: "RUN_COMPLETED",
            RecoveryResolution.CREATE_CORRECTIVE_PLAN: "RUN_PLANNING_STARTED",
            RecoveryResolution.CANCEL: "RUN_CANCELLED",
        }
        event_type = event_by_resolution.get(command.resolution)
        if event_type is None:
            return
        unit_of_work.audits.append(
            AuditEventRecord(
                account_id=None,
                run_id=command.run_id,
                action_id=(None if context.get("action_id") is None else str(context["action_id"])),
                actor_type="SYSTEM",
                actor_id="run_lifecycle",
                actor_display="Run lifecycle",
                event_type=event_type,
                outcome=result.result_code,
                metadata_json=metadata,
                created_at_ms=now_ms,
            )
        )

    def _append_terminal_message(
        self,
        unit_of_work: UnitOfWork,
        conversation_id: str,
        run_id: str,
        result_kind: str | None,
        now_ms: int,
    ) -> None:
        if self._next_id is None or result_kind not in {"PARTIAL", "FAILED", "CANCELLED"}:
            raise RuntimeError("terminal recovery requires message identity and result kind")
        message = self._build_terminal_message(
            BuildTerminalMessageQueryV1(
                run_id=run_id,
                result_kind=result_kind,  # type: ignore[arg-type]
            )
        )
        unit_of_work.messages.append_terminal_assistant_message(
            MessageRecord(
                id=self._next_id(),
                conversation_id=conversation_id,
                run_id=run_id,
                role=message.role,
                content=message.content,
                created_at_ms=now_ms,
            )
        )

    def _stage_continuation(
        self,
        unit_of_work: UnitOfWork,
        *,
        command: ResolveRecoveryCommandV1,
        context: RecoveryContextV1,
        target_status: RunStatusV1,
        now_ms: int,
    ) -> str | None:
        if self._next_id is None or self._resume_target_registry is None:
            return None
        binding = unit_of_work.checkpoints.load_workflow_binding(command.run_id)
        checkpoint = (
            None
            if binding is None
            else unit_of_work.checkpoints.load_same_run_checkpoint(
                command.run_id, binding.langgraph_thread_id
            )
        )
        if binding is None or checkpoint is None:
            raise RuntimeError("recovery continuation requires a durable workflow checkpoint")
        stage_by_status: dict[RunStatusV1, MainResumeStageIdV1] = {
            RunStatusV1.VERIFYING: "VERIFICATION",
            RunStatusV1.PLANNING: "PLANNING_ENTRY",
            RunStatusV1.CANCEL_REQUESTED: "CANCEL_RESOLUTION",
        }
        resume_target = context.get("registered_resume_target")
        if target_status in stage_by_status or resume_target is None:
            resume_target = self._resume_target_registry.issue_main_stage(
                binding.graph_profile,
                stage_by_status.get(target_status, "PREFLIGHT"),
                binding.graph_version,
            )
        unit_of_work.checkpoints.store_same_run_checkpoint(
            replace(
                checkpoint,
                registered_resume_target=resume_target,
                created_at_ms=now_ms,
            )
        )
        handoff_id = self._next_id()
        unit_of_work.workflow_handoffs.stage_pending(
            WorkflowHandoffStageV1(
                schema_version=1,
                handoff_id=handoff_id,
                trigger_command_id=command.command_id,
                execution=RunExecutionRefV1(
                    schema_version=1,
                    execution_kind="RESUME",
                    run_id=command.run_id,
                    langgraph_thread_id=binding.langgraph_thread_id,
                    graph_profile=binding.graph_profile,
                    graph_version=binding.graph_version,
                    requested_mode=binding.requested_mode,
                    resume_target=resume_target,
                ),
                checkpoint_id=checkpoint.checkpoint_id,
                checkpoint_generation=checkpoint.checkpoint_generation,
                control_kind="NONE",
                control=None,
                control_payload_hash=None,
            )
        )
        return handoff_id

    @staticmethod
    def _replay_or_reject_duplicate(
        unit_of_work: UnitOfWork,
        command: ResolveRecoveryCommandV1,
        receipt: CommandReceiptRecord,
    ) -> ResolveRecoveryResult:
        if receipt.request_hash != command.request_hash:
            run = unit_of_work.runs.get(command.run_id)
            return ResolveRecoveryResult(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                current_status=run.status.value if run else "UNKNOWN",
                current_version=run.version if run else 0,
                next_allowed_commands=(),
                conflict_detail="command_id already exists with a different request_hash",
            )
        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            raise RuntimeError("RECEIVED receipt requires transaction recovery before replay")
        payload = loads(receipt.response_json)
        payload["next_allowed_commands"] = tuple(payload.get("next_allowed_commands", ()))
        return ResolveRecoveryResult(**payload)

    @staticmethod
    def _finish_result(
        unit_of_work: UnitOfWork,
        command: ResolveRecoveryCommandV1,
        result: ResolveRecoveryResult,
        now_ms: int,
    ) -> None:
        unit_of_work.command_receipts.store_result(
            command_id=command.command_id,
            applied=result.applied,
            result_code=ResultCode(result.result_code),
            result_version=result.current_version,
            response_json=dumps(asdict(result), sort_keys=True),
            completed_at_ms=now_ms,
        )
