"""Canonical persisted ResumeAfterReauth application authority."""

from typing import cast

from google_work_agent.application.cancel_intent import has_durable_cancel_intent
from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryCommand,
    RequireRecoveryHandler,
)
from google_work_agent.application.use_cases.run.resume_run import (
    ResumeAuthority,
    ResumeRunCommand,
    ResumeRunHandler,
    ResumeRunResult,
    _PersistedRunDecision,
)
from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.results import CommandResult, ResultCode
from google_work_agent.domain.run.model import RunCommand, RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.resume_after_reauth import (
    transition_resume_after_reauth,
)
from google_work_agent.ports.persistence.execution_attempt_repository import active_attempt_tuple
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

ResumeAfterReauthCommand = ResumeRunCommand
ResumeAfterReauthResult = ResumeRunResult
_ResumeDecision = CommandResult[RunStatusV1, RunCommand] | _PersistedRunDecision


class ResumeAfterReauthHandler(ResumeRunHandler):
    """Own the reauth child-fact matrix, transition, recovery fallback, and replay fence."""

    def __call__(
        self,
        command: ResumeAfterReauthCommand,
        *,
        request_id: str,
        resume_payload: dict[str, object] | None = None,
    ) -> ResumeAfterReauthResult:
        if command.resume_kind != "REAUTH_COMPLETED":
            raise ValueError("ResumeAfterReauthHandler accepts REAUTH_COMPLETED only")
        return super().__call__(
            command,
            request_id=request_id,
            resume_payload=resume_payload,
        )

    def _apply_canonical_transition(
        self,
        unit_of_work: UnitOfWork,
        command: ResumeRunCommand,
        current_version: int,
        authority: ResumeAuthority | None,
        *,
        reauth_dispatch_uncertain: bool,
        now_ms: int,
    ) -> tuple[_ResumeDecision, bool]:
        if authority is None:
            raise RuntimeError("persisted reauth authority is unavailable")
        run = unit_of_work.runs.get(command.run_id)
        if run is None:
            raise LookupError(f"run not found: {command.run_id}")
        resume_status = RunStatusV1(cast(str, authority["resume_status"]))
        binding = unit_of_work.checkpoints.load_workflow_binding(command.run_id)
        checkpoint = (
            None
            if binding is None
            else unit_of_work.checkpoints.load_same_run_checkpoint(
                command.run_id, binding.langgraph_thread_id
            )
        )
        target = None if checkpoint is None else checkpoint.registered_resume_target
        plans = tuple(
            plan
            for plan in current_plan_tuple(unit_of_work.plans, command.run_id)
            if getattr(getattr(plan, "status", None), "value", None) != "SUPERSEDED"
        )
        plan = plans[0] if len(plans) == 1 else None
        actions = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)
        approval_history = getattr(unit_of_work, "approval_history", None)
        approvals = (
            ()
            if approval_history is None
            else tuple(
                approval
                for action in actions
                for approval in approval_history.list_for_action(action.id)
            )
        )
        attempt_repository = getattr(unit_of_work, "execution_attempts", None)
        attempts = tuple(
            attempt
            for approval in approvals
            for attempt in (
                ()
                if attempt_repository is None
                else active_attempt_tuple(attempt_repository, approval.id)
            )
        )
        binding_is_current = bool(
            binding is not None
            and checkpoint is not None
            and target is not None
            and checkpoint.run_id == run.id
            and checkpoint.langgraph_thread_id == binding.langgraph_thread_id
            and checkpoint.graph_profile == binding.graph_profile
            and checkpoint.graph_version == binding.graph_version
            and target.graph_profile == binding.graph_profile
            and target.graph_version == binding.graph_version
        )
        action_statuses = tuple(ActionStatusV1(action.status) for action in actions)
        attempt_statuses = tuple(attempt.status for attempt in attempts)
        has_legacy_read_executing = any(
            getattr(action, "effect_type", None) == EffectType.READ.value
            and ActionStatusV1(action.status) is ActionStatusV1.EXECUTING
            for action in actions
        )
        delivery_uncertain = any(
            ActionStatusV1(action.status)
            in {ActionStatusV1.EXECUTED, ActionStatusV1.UNKNOWN_RESULT}
            for action in actions
        ) or any(
            attempt.status
            in {
                ExecutionAttemptStatusV1.EXECUTING,
                ExecutionAttemptStatusV1.UNKNOWN_RESULT,
                ExecutionAttemptStatusV1.SUCCEEDED,
            }
            for attempt in attempts
        )
        try:
            next_status = transition_resume_after_reauth(
                run.status,
                resume_status=resume_status,
                target_kind="" if target is None else target.kind,
                target_stage=getattr(target, "stage_id", None),
                binding_is_current=binding_is_current,
                action_statuses=action_statuses,
                attempt_statuses=attempt_statuses,
                has_legacy_read_executing=has_legacy_read_executing,
                delivery_uncertain=delivery_uncertain,
                cancel_intent_active=_has_cancel_intent(unit_of_work, run.id),
            )
        except RunTransitionRejected:
            return self._require_recovery(
                unit_of_work=unit_of_work,
                command=command,
                run=run,
                resume_status=resume_status,
                target_stage=getattr(target, "stage_id", None),
                now_ms=now_ms,
            )
        if run.version != current_version:
            return (
                CommandResult(
                    False,
                    ResultCode.VERSION_CONFLICT,
                    run.status,
                    run.version,
                    (),
                    "expected_version does not match current_version",
                ),
                False,
            )
        if not unit_of_work.runs.update_if_version_and_status(
            run.id,
            run.version,
            frozenset({run.status}),
            {"status": next_status.value, "version": run.version + 1},
        ):
            raise RuntimeError("validated ResumeAfterReauth CAS failed")
        restored: CommandResult[RunStatusV1, RunCommand] = CommandResult(
            True, ResultCode.TRANSITION_APPLIED, next_status, run.version + 1, ()
        )
        if restored.current_status is RunStatusV1.RECOVERY_REQUIRED:
            return restored, False
        if not reauth_dispatch_uncertain:
            return restored, True

        fingerprint = calculate_canonical_json_hash(
            {
                "command_id": command.command_id,
                "run_id": command.run_id,
                "pre_recovery_status": restored.current_status.value,
            }
        )
        recovery = RequireRecoveryHandler.apply_in_unit_of_work(
            unit_of_work,
            RequireRecoveryCommand(
                run_id=command.run_id,
                expected_version=restored.current_version,
                command_id=f"system:reauth-dispatch-uncertain-recovery:{command.command_id}",
                request_hash=fingerprint,
                reason="CHECKPOINT_MISMATCH",
                scope="RUN",
                recovery_fingerprint=fingerprint,
                contract_or_checkpoint_fingerprint=fingerprint,
            ),
            now_ms=now_ms,
        )
        if not recovery.applied:
            raise RuntimeError("reauth recovery fail-safe transition was not applied")
        return (
            _PersistedRunDecision(
                applied=recovery.applied,
                result_code=ResultCode(recovery.result_code),
                current_status=RunStatusV1(recovery.current_status),
                current_version=recovery.current_version,
                conflict_detail=recovery.conflict_detail,
            ),
            False,
        )
    @staticmethod
    def _require_recovery(
        *,
        unit_of_work: UnitOfWork,
        command: ResumeRunCommand,
        run: object,
        resume_status: RunStatusV1,
        target_stage: object,
        now_ms: int,
    ) -> tuple[_ResumeDecision, bool]:
        fingerprint = calculate_canonical_json_hash(
            {
                "command_id": command.command_id,
                "run_id": command.run_id,
                "resume_status": resume_status.value,
                "target_stage": target_stage,
            }
        )
        recovery = RequireRecoveryHandler.apply_in_unit_of_work(
            unit_of_work,
            RequireRecoveryCommand(
                run_id=command.run_id,
                expected_version=run.version,  # type: ignore[attr-defined]
                command_id=f"system:reauth-target-mismatch:{command.command_id}",
                request_hash=fingerprint,
                reason="CHECKPOINT_MISMATCH",
                scope="RUN",
                recovery_fingerprint=fingerprint,
                contract_or_checkpoint_fingerprint=fingerprint,
            ),
            now_ms=now_ms,
        )
        return (
            _PersistedRunDecision(
                bool(recovery.applied),
                ResultCode(recovery.result_code),
                RunStatusV1(recovery.current_status),
                recovery.current_version,
                recovery.conflict_detail,
            ),
            False,
        )


def _has_cancel_intent(unit_of_work: UnitOfWork, run_id: str) -> bool:
    return has_durable_cancel_intent(unit_of_work.cancel_intents, run_id)


__all__ = [
    "ResumeAfterReauthCommand",
    "ResumeAfterReauthHandler",
    "ResumeAfterReauthResult",
]
