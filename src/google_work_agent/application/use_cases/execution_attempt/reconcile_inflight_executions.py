"""Startup-only reconciliation for durable post-Begin execution facts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from google_work_agent.application.use_cases.execution_attempt.mark_unknown_result import (
    MarkUnknownResultCommand,
    MarkUnknownResultHandler,
)
from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryCommand,
    RequireRecoveryHandler,
)
from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetValidator
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports import DeliveryCertainty, UUIDPort
from google_work_agent.ports.persistence.execution_attempt_repository import (
    ExecutionReconciliationCandidateV1,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionRefV1,
    WorkflowHandoffStageV1,
)


@dataclass(frozen=True, slots=True)
class ReconcileInflightExecutionsCommand:
    schema_version: Literal[1]
    limit: int


@dataclass(frozen=True, slots=True)
class ReconcileInflightExecutionsResult:
    schema_version: Literal[1]
    processed_count: int
    progressed_count: int
    has_more: bool


class ReconcileInflightExecutionsHandler:
    """Reconcile process-loss facts without ever resending the original Write."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        mark_unknown_result: MarkUnknownResultHandler,
        require_recovery: RequireRecoveryHandler,
        resume_target_registry: ResumeTargetValidator,
        id_generator: UUIDPort,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._mark_unknown_result = mark_unknown_result
        self._require_recovery = require_recovery
        self._resume_target_registry = resume_target_registry
        self._id_generator = id_generator

    def __call__(
        self, command: ReconcileInflightExecutionsCommand
    ) -> ReconcileInflightExecutionsResult:
        if command.schema_version != 1 or not 1 <= command.limit <= 256:
            raise ValueError("reconciliation limit must be between 1 and 256")
        with self._unit_of_work_factory() as unit_of_work:
            candidates = unit_of_work.execution_attempts.list_reconciliation_candidates(
                command.limit
            )
        progressed = sum(self._reconcile(candidate) for candidate in candidates)
        return ReconcileInflightExecutionsResult(
            schema_version=1,
            processed_count=len(candidates),
            progressed_count=progressed,
            has_more=len(candidates) == command.limit,
        )

    def _reconcile(self, candidate: ExecutionReconciliationCandidateV1) -> int:
        if candidate.kind == "POST_BEGIN_ORPHAN":
            with self._unit_of_work_factory() as unit_of_work:
                action = unit_of_work.actions.get_by_id(candidate.action_id)
                attempt = unit_of_work.execution_attempts.get_by_id(candidate.execution_attempt_id)
            if action is None or attempt is None:
                return 0
            command_id = f"system:execution-attempt-reconcile:{candidate.execution_attempt_id}"
            result = self._mark_unknown_result(
                MarkUnknownResultCommand(
                    command_id=command_id,
                    request_hash=calculate_canonical_json_hash(
                        {"command_id": command_id, "kind": candidate.kind}
                    ),
                    action_id=action.id,
                    attempt_id=attempt.id,
                    expected_action_version=action.version,
                    expected_attempt_version=attempt.version,
                    delivery_certainty=DeliveryCertainty.MAY_HAVE_BEEN_SENT,
                    error_code="POST_BEGIN_PROCESS_LOSS",
                    error_detail="process ended after BeginExecutionAttempt commit",
                )
            )
            return int(result.applied)
        if candidate.kind == "UNKNOWN_RESULT_UNRESOLVED":
            return int(self._require_unknown_recovery(candidate))
        if candidate.kind == "EXECUTED_AWAITING_VERIFICATION":
            return int(self._stage_continuation(candidate, "VERIFICATION", ":verification"))
        if candidate.kind == "FAILED_AWAITING_CONTINUATION":
            with self._unit_of_work_factory() as unit_of_work:
                run = unit_of_work.runs.get(candidate.run_id)
                plans = unit_of_work.plans.list_by_run(candidate.run_id)
                plan = max(
                    plans, key=lambda item: (item.revision_no, item.created_at_ms), default=None
                )
                actions = () if plan is None else unit_of_work.actions.list_by_plan(plan.id)
            stage = (
                "CANCEL_RESOLUTION"
                if run is not None and run.status is RunStatusV1.CANCEL_REQUESTED
                else "PREFLIGHT"
                if any(item.status == ActionStatusV1.APPROVED.value for item in actions)
                else None
            )
            return (
                0
                if stage is None
                else int(self._stage_continuation(candidate, stage, ":post-failed"))
            )
        return 0

    def _require_unknown_recovery(self, candidate: ExecutionReconciliationCandidateV1) -> bool:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(candidate.run_id)
        if run is None or run.status is RunStatusV1.RECOVERY_REQUIRED:
            return False
        command_id = (
            f"system:execution-attempt-reconcile:{candidate.execution_attempt_id}:require-recovery"
        )
        fingerprint = calculate_canonical_json_hash(
            {
                "execution_attempt_id": candidate.execution_attempt_id,
                "action_id": candidate.action_id,
                "run_id": candidate.run_id,
            }
        )
        result = self._require_recovery(
            RequireRecoveryCommand(
                run_id=candidate.run_id,
                expected_version=run.version,
                command_id=command_id,
                request_hash=calculate_canonical_json_hash(
                    {"command_id": command_id, "fingerprint": fingerprint}
                ),
                reason="UNKNOWN_RESULT",
                scope="ACTION",
                recovery_fingerprint=fingerprint,
                action_id=candidate.action_id,
                execution_attempt_id=candidate.execution_attempt_id,
            )
        )
        return result.applied

    def _stage_continuation(
        self,
        candidate: ExecutionReconciliationCandidateV1,
        stage_id: str,
        suffix: str,
    ) -> bool:
        trigger = f"system:execution-attempt-reconcile:{candidate.execution_attempt_id}{suffix}"
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.workflow_handoffs.get_by_trigger_command_id(trigger)
            if existing is not None:
                return False
            binding = unit_of_work.checkpoints.load_workflow_binding(candidate.run_id)
            if binding is None:
                return False
            checkpoint = unit_of_work.checkpoints.load_same_run_checkpoint(
                candidate.run_id, binding.langgraph_thread_id
            )
            if checkpoint is None:
                return False
            target = self._resume_target_registry.issue_main_stage(
                binding.graph_profile, stage_id, binding.graph_version
            )
            unit_of_work.workflow_handoffs.stage_pending(
                WorkflowHandoffStageV1(
                    schema_version=1,
                    handoff_id=self._id_generator.next_id(),
                    trigger_command_id=trigger,
                    execution=RunExecutionRefV1(
                        schema_version=1,
                        execution_kind="RESUME",
                        run_id=candidate.run_id,
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
            unit_of_work.commit()
            return True


def drain_inflight_executions_to_quiescence(
    handler: ReconcileInflightExecutionsHandler,
    *,
    batch_limit: int = 32,
    max_passes: int = 1000,
) -> int:
    for pass_index in range(1, max_passes + 1):
        result = handler(ReconcileInflightExecutionsCommand(schema_version=1, limit=batch_limit))
        if not result.has_more or result.progressed_count == 0:
            return pass_index
    raise RuntimeError("inflight execution startup drain did not reach quiescence")


ReconcileInflightExecutionsCommandV1 = ReconcileInflightExecutionsCommand
ReconcileInflightExecutionsResultV1 = ReconcileInflightExecutionsResult


__all__ = [
    "ReconcileInflightExecutionsCommand",
    "ReconcileInflightExecutionsCommandV1",
    "ReconcileInflightExecutionsHandler",
    "ReconcileInflightExecutionsResult",
    "ReconcileInflightExecutionsResultV1",
    "drain_inflight_executions_to_quiescence",
]
