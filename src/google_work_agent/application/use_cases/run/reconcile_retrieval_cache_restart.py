"""Convert typed retrieval-cache loss into one durable restart handoff."""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal

from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetIssuer
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
    ScheduleRunExecutionHandler,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.run.model import is_preempting_run_status
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.checkpoint_port import CheckpointPort
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RetrievalCacheRestartControlV1,
    RunExecutionRefV1,
    WorkflowHandoffStageV1,
)
from google_work_agent.ports.system.run_retrieval_cache_port import RunRetrievalCachePort


@dataclass(frozen=True, slots=True)
class ReconcileRetrievalCacheRestartCommandV1:
    schema_version: Literal[1]
    run_id: str


@dataclass(frozen=True, slots=True)
class ReconcileRetrievalCacheRestartResultV1:
    schema_version: Literal[1]
    outcome: Literal["NO_RESTART_REQUIRED", "RESTART_STAGED", "EXISTING_RESTART"]
    checkpoint_generation: int
    handoff_id: str | None


class ReconcileRetrievalCacheRestartHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        checkpoint: CheckpointPort,
        retrieval_cache: RunRetrievalCachePort,
        resume_target_registry: ResumeTargetIssuer,
        schedule_run_execution: ScheduleRunExecutionHandler,
        id_factory: Callable[[], str],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._checkpoint = checkpoint
        self._retrieval_cache = retrieval_cache
        self._resume_target_registry = resume_target_registry
        self._schedule_run_execution = schedule_run_execution
        self._id_factory = id_factory

    def __call__(
        self, command: ReconcileRetrievalCacheRestartCommandV1
    ) -> ReconcileRetrievalCacheRestartResultV1:
        if command.schema_version != 1:
            raise ValueError("unsupported retrieval-cache reconciliation schema")
        binding = self._checkpoint.load_workflow_binding(command.run_id)
        if binding is None:
            raise LookupError("workflow binding is unavailable")
        checkpoint = self._checkpoint.load_same_run_checkpoint(
            command.run_id, binding.langgraph_thread_id
        )
        if checkpoint is None:
            raise LookupError("workflow checkpoint is unavailable")
        if self._is_preempted(command.run_id):
            return ReconcileRetrievalCacheRestartResultV1(
                1, "NO_RESTART_REQUIRED", checkpoint.checkpoint_generation, None
            )

        invalid = []
        for requirement in checkpoint.retrieval_cache_requirements:
            resolved = self._retrieval_cache.resolve_read_result(
                requirement.read_result_handle,
                command.run_id,
                requirement.route_id,
                requirement.query_identity_hash,
            )
            if resolved.status in {"MISSING", "CROSS_RUN", "BINDING_MISMATCH"}:
                invalid.append(requirement)
        if not invalid:
            return ReconcileRetrievalCacheRestartResultV1(
                1, "NO_RESTART_REQUIRED", checkpoint.checkpoint_generation, None
            )

        trigger = (
            f"system:retrieval-cache-restart:{command.run_id}:{checkpoint.checkpoint_generation}"
        )
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(command.run_id)
            if run is None or is_preempting_run_status(run.status):
                return ReconcileRetrievalCacheRestartResultV1(
                    1, "NO_RESTART_REQUIRED", checkpoint.checkpoint_generation, None
                )
            existing = unit_of_work.workflow_handoffs.get_by_trigger_command_id(trigger)
            if existing is not None:
                return ReconcileRetrievalCacheRestartResultV1(
                    1,
                    "EXISTING_RESTART",
                    checkpoint.checkpoint_generation,
                    existing.handoff_id,
                )
            fingerprint = calculate_canonical_json_hash(
                [asdict(requirement) for requirement in invalid]
            )
            control = RetrievalCacheRestartControlV1(
                kind="RETRIEVAL_CACHE_RESTART",
                lost_checkpoint_id=checkpoint.checkpoint_id,
                lost_handle_fingerprint=fingerprint,
            )
            handoff_id = self._id_factory()
            target = self._resume_target_registry.issue_main_stage(
                binding.graph_profile, "RETRIEVAL_ENTRY", binding.graph_version
            )
            unit_of_work.workflow_handoffs.stage_pending(
                WorkflowHandoffStageV1(
                    schema_version=1,
                    handoff_id=handoff_id,
                    trigger_command_id=trigger,
                    execution=RunExecutionRefV1(
                        schema_version=1,
                        execution_kind="RESUME",
                        run_id=command.run_id,
                        langgraph_thread_id=binding.langgraph_thread_id,
                        graph_profile=binding.graph_profile,
                        graph_version=binding.graph_version,
                        requested_mode=binding.requested_mode,
                        resume_target=target,
                    ),
                    checkpoint_id=checkpoint.checkpoint_id,
                    checkpoint_generation=checkpoint.checkpoint_generation,
                    control_kind="RETRIEVAL_CACHE_RESTART",
                    control=control,
                    control_payload_hash=calculate_canonical_json_hash(asdict(control)),
                )
            )
            unit_of_work.commit()
        self._schedule_run_execution(ScheduleRunExecutionCommand(handoff_id=handoff_id))
        return ReconcileRetrievalCacheRestartResultV1(
            1, "RESTART_STAGED", checkpoint.checkpoint_generation, handoff_id
        )

    def _is_preempted(self, run_id: str) -> bool:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(run_id)
        return run is None or is_preempting_run_status(run.status)


__all__ = [
    "ReconcileRetrievalCacheRestartCommandV1",
    "ReconcileRetrievalCacheRestartHandler",
    "ReconcileRetrievalCacheRestartResultV1",
]
