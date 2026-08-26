"""Claim and submit one durable workflow execution admission."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.use_cases.run.resume_confirmation import (
    ResumeTargetValidator,
)
from google_work_agent.domain.run.model import TERMINAL_RUN_STATUSES
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.checkpoint_port import CheckpointPort
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
    WorkflowExecutionAdmissionV1,
    WorkflowExecutionBindingV1,
    WorkflowExecutionSubmissionV2,
    WorkflowHandoffV1,
)
from google_work_agent.ports.system.workflow_execution_port import WorkflowExecutionPort

type UnitOfWorkFactory = Callable[[], UnitOfWork]
type EffectiveBindingResolver = Callable[
    [WorkflowHandoffV1, str], WorkflowExecutionBindingV1 | None
]
type ScheduleRunExecutionResult = RunExecutionAcceptedV1

_RECOVERY_PREEMPTING_STATUSES = {
    "REAUTH_REQUIRED",
    "RECOVERY_REQUIRED",
    "CANCEL_REQUESTED",
    "COMPLETED",
    "CANCELLED",
    "FAILED",
    "BLOCKED",
}


@dataclass(frozen=True, slots=True)
class ScheduleRunExecutionCommand:
    handoff_id: str
    submission_kind: str = "NORMAL_HANDOFF"


class CheckpointEffectiveBindingResolver:
    """Resolve recovery only from the latest typed active-lineage checkpoint.

    Target legality (main resume stage / profile-to-compiled-subgraph /
    node registration) is delegated entirely to ResumeTargetRegistry via the
    shared ResumeTargetValidator Protocol -- this resolver owns only
    checkpoint/handoff lineage matching, never a second copy of registry
    authority.
    """

    def __init__(
        self,
        checkpoint_port: CheckpointPort,
        resume_target_registry: ResumeTargetValidator,
    ) -> None:
        self._checkpoint_port = checkpoint_port
        self._resume_target_registry = resume_target_registry

    def __call__(
        self, handoff: WorkflowHandoffV1, submission_kind: str
    ) -> WorkflowExecutionBindingV1 | None:
        if submission_kind == "NORMAL_HANDOFF":
            execution = handoff.execution
            return WorkflowExecutionBindingV1(
                schema_version=1,
                execution_kind=execution.execution_kind,
                run_id=execution.run_id,
                langgraph_thread_id=execution.langgraph_thread_id,
                graph_profile=execution.graph_profile,
                graph_version=execution.graph_version,
                requested_mode=execution.requested_mode,
                checkpoint_id=handoff.checkpoint_id,
                checkpoint_generation=handoff.checkpoint_generation,
                resume_target=execution.resume_target,
            )
        if submission_kind != "CONSUMED_CONTINUATION_RECOVERY":
            return None
        checkpoint = self._checkpoint_port.load_same_run_checkpoint(
            handoff.execution.run_id,
            handoff.execution.langgraph_thread_id,
        )
        if checkpoint is None or not _checkpoint_authorizes_recovery(
            checkpoint, handoff, self._resume_target_registry
        ):
            return None
        return WorkflowExecutionBindingV1(
            schema_version=1,
            execution_kind="RESUME",
            run_id=checkpoint.run_id,
            langgraph_thread_id=checkpoint.langgraph_thread_id,
            graph_profile=checkpoint.graph_profile,
            graph_version=checkpoint.graph_version,
            requested_mode=handoff.execution.requested_mode,
            checkpoint_id=checkpoint.checkpoint_id,
            checkpoint_generation=checkpoint.checkpoint_generation,
            resume_target=checkpoint.registered_resume_target,
        )


class ScheduleRunExecutionHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        workflow_execution: WorkflowExecutionPort,
        id_factory: Callable[[], str],
        effective_binding_resolver: EffectiveBindingResolver | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._workflow_execution = workflow_execution
        self._id_factory = id_factory
        self._effective_binding_resolver = effective_binding_resolver

    def __call__(self, command: ScheduleRunExecutionCommand) -> RunExecutionAcceptedV1:
        if command.submission_kind not in {
            "NORMAL_HANDOFF",
            "CONSUMED_CONTINUATION_RECOVERY",
        }:
            raise ValueError("unsupported workflow handoff submission kind")
        with self._unit_of_work_factory() as unit_of_work:
            handoff = unit_of_work.workflow_handoffs.get(command.handoff_id)
            if handoff is None:
                return _rejected("NOT_COMMITTED")
            run = unit_of_work.runs.get_by_id(handoff.execution.run_id)
            if run is None or run.status in TERMINAL_RUN_STATUSES:
                if handoff.execution_admission is None and handoff.status not in {
                    "CONSUMED",
                    "SUPERSEDED",
                }:
                    unit_of_work.workflow_handoffs.mark_superseded(
                        handoff.handoff_id, handoff.version, "RUN_NOT_EXECUTABLE"
                    )
                    unit_of_work.commit()
                return _rejected("NOT_COMMITTED")
            if (
                command.submission_kind == "CONSUMED_CONTINUATION_RECOVERY"
                and run.status.value in _RECOVERY_PREEMPTING_STATUSES
            ):
                return _rejected("BINDING_MISMATCH")
            existing = handoff.execution_admission
            if existing is not None and existing.expected_run_version != run.version:
                unit_of_work.workflow_handoffs.release_execution_admission(
                    handoff.handoff_id,
                    handoff.version,
                    existing.admission_id,
                    "AUTHORITY_EPOCH_CHANGED",
                )
                unit_of_work.commit()
                return _rejected("BINDING_MISMATCH")
            if existing is not None:
                admission = existing
            else:
                binding = self._resolve_binding(handoff, command.submission_kind)
                if binding is None or not _binding_matches_handoff(binding, handoff):
                    return _rejected("BINDING_MISMATCH")
                admission = WorkflowExecutionAdmissionV1(
                    schema_version=1,
                    admission_id=self._id_factory(),
                    handoff_id=handoff.handoff_id,
                    handoff_run_sequence=handoff.run_sequence,
                    submission_kind=command.submission_kind,  # type: ignore[arg-type]
                    effective_binding=binding,
                    expected_run_version=run.version,
                )
                handoff = unit_of_work.workflow_handoffs.claim_execution_admission(
                    handoff.handoff_id, handoff.version, admission
                )
                persisted_admission = handoff.execution_admission
                if persisted_admission is None:
                    raise RuntimeError("admission claim did not persist an admission")
                admission = persisted_admission
                unit_of_work.commit()

        result = self._workflow_execution.submit(
            WorkflowExecutionSubmissionV2(schema_version=2, admission=admission)
        )
        if result.accepted:
            return result
        with self._unit_of_work_factory() as unit_of_work:
            current = unit_of_work.workflow_handoffs.get(command.handoff_id)
            if (
                current is not None
                and current.execution_admission is not None
                and current.execution_admission.admission_id == admission.admission_id
            ):
                unit_of_work.workflow_handoffs.release_execution_admission(
                    current.handoff_id,
                    current.version,
                    admission.admission_id,
                    result.reason_code,  # type: ignore[arg-type]
                )
                unit_of_work.commit()
        return result

    def _resolve_binding(
        self, handoff: WorkflowHandoffV1, submission_kind: str
    ) -> WorkflowExecutionBindingV1 | None:
        if self._effective_binding_resolver is not None:
            return self._effective_binding_resolver(handoff, submission_kind)
        if submission_kind != "NORMAL_HANDOFF":
            return None
        execution = handoff.execution
        return WorkflowExecutionBindingV1(
            schema_version=1,
            execution_kind=execution.execution_kind,
            run_id=execution.run_id,
            langgraph_thread_id=execution.langgraph_thread_id,
            graph_profile=execution.graph_profile,
            graph_version=execution.graph_version,
            requested_mode=execution.requested_mode,
            checkpoint_id=handoff.checkpoint_id,
            checkpoint_generation=handoff.checkpoint_generation,
            resume_target=execution.resume_target,
        )


def _binding_matches_handoff(
    binding: WorkflowExecutionBindingV1, handoff: WorkflowHandoffV1
) -> bool:
    execution = handoff.execution
    return (
        binding.run_id == execution.run_id
        and binding.langgraph_thread_id == execution.langgraph_thread_id
        and binding.graph_profile == execution.graph_profile
        and binding.graph_version == execution.graph_version
        and binding.requested_mode == execution.requested_mode
    )


def _checkpoint_authorizes_recovery(
    checkpoint: object,
    handoff: WorkflowHandoffV1,
    resume_target_registry: ResumeTargetValidator,
) -> bool:
    from google_work_agent.ports.system.contracts.checkpoint import GraphCheckpointEnvelopeV1

    if not isinstance(checkpoint, GraphCheckpointEnvelopeV1):
        return False
    execution = handoff.execution
    if (
        checkpoint.run_id != execution.run_id
        or checkpoint.langgraph_thread_id != execution.langgraph_thread_id
        or checkpoint.graph_profile != execution.graph_profile
        or checkpoint.graph_version != execution.graph_version
        or checkpoint.active_handoff_id != handoff.handoff_id
        or checkpoint.active_handoff_run_sequence != handoff.run_sequence
        or checkpoint.registered_resume_target is None
        or checkpoint.checkpoint_generation < (handoff.applied_checkpoint_generation or 0)
    ):
        return False
    target = checkpoint.registered_resume_target
    if (
        target.graph_profile != checkpoint.graph_profile
        or target.graph_version != checkpoint.graph_version
    ):
        return False
    try:
        resume_target_registry.validate(target)
    except ValueError:
        return False
    return True


def _rejected(reason_code: str) -> RunExecutionAcceptedV1:
    return RunExecutionAcceptedV1(
        schema_version=1,
        accepted=False,
        reason_code=reason_code,  # type: ignore[arg-type]
    )
