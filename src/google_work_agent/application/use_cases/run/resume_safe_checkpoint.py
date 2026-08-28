"""Resume only a matrix-allowed same-Run safe checkpoint."""

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.cancel_intent import has_durable_cancel_intent
from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetValidator
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
    ScheduleRunExecutionHandler,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.run.model import Run, RunStatusV1
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionRefV1,
    WorkflowHandoffStageV1,
)

_ALLOWED_SOURCE_STATUSES = frozenset(
    {
        RunStatusV1.CREATED,
        RunStatusV1.ANALYZING,
        RunStatusV1.RETRIEVING,
        RunStatusV1.PLANNING,
    }
)
_UNRESOLVED_WRITE_STATUSES = frozenset(
    {ActionStatusV1.EXECUTING.value, ActionStatusV1.UNKNOWN_RESULT.value}
)


@dataclass(frozen=True, slots=True)
class ResumeSafeCheckpointCommand:
    command_id: str
    run_id: str
    expected_run_version: int


@dataclass(frozen=True, slots=True)
class ResumeSafeCheckpointResult:
    applied: bool
    result_code: str
    run_id: str
    run_status: str
    run_version: int
    handoff_id: str | None
    conflict_detail: str | None = None


class ResumeSafeCheckpointHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        resume_target_registry: ResumeTargetValidator,
        schedule_run_execution: ScheduleRunExecutionHandler,
        id_factory: Callable[[], str],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._resume_target_registry = resume_target_registry
        self._schedule_run_execution = schedule_run_execution
        self._id_factory = id_factory

    def __call__(self, command: ResumeSafeCheckpointCommand) -> ResumeSafeCheckpointResult:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(command.run_id)
            if run is None:
                raise LookupError(f"run not found: {command.run_id}")
            conflict = self._guard(unit_of_work, command, run.status, run.version)
            if conflict is not None:
                return ResumeSafeCheckpointResult(
                    False,
                    conflict[0],
                    run.id,
                    run.status.value,
                    run.version,
                    None,
                    conflict[1],
                )
            binding = unit_of_work.checkpoints.load_workflow_binding(run.id)
            if binding is None:
                return self._not_allowed(run, "workflow binding is unavailable")
            checkpoint = unit_of_work.checkpoints.load_same_run_checkpoint(
                run.id, binding.langgraph_thread_id
            )
            if (
                checkpoint is None
                or checkpoint.run_id != run.id
                or checkpoint.langgraph_thread_id != binding.langgraph_thread_id
                or checkpoint.graph_profile != binding.graph_profile
                or checkpoint.graph_version != binding.graph_version
                or checkpoint.registered_resume_target is None
            ):
                return self._not_allowed(run, "checkpoint binding does not match the Run")
            try:
                self._resume_target_registry.validate(checkpoint.registered_resume_target)
            except (LookupError, ValueError):
                return self._not_allowed(run, "registered resume target is invalid")
            existing = unit_of_work.workflow_handoffs.get_by_trigger_command_id(command.command_id)
            if existing is None:
                handoff_id = self._id_factory()
                unit_of_work.workflow_handoffs.stage_pending(
                    WorkflowHandoffStageV1(
                        schema_version=1,
                        handoff_id=handoff_id,
                        trigger_command_id=command.command_id,
                        execution=RunExecutionRefV1(
                            schema_version=1,
                            execution_kind="RESUME",
                            run_id=run.id,
                            langgraph_thread_id=binding.langgraph_thread_id,
                            graph_profile=binding.graph_profile,
                            graph_version=binding.graph_version,
                            requested_mode=binding.requested_mode,
                            resume_target=checkpoint.registered_resume_target,
                        ),
                        checkpoint_id=checkpoint.checkpoint_id,
                        checkpoint_generation=checkpoint.checkpoint_generation,
                        control_kind="NONE",
                        control=None,
                        control_payload_hash=None,
                    )
                )
                unit_of_work.commit()
            else:
                handoff_id = existing.handoff_id
        accepted = self._schedule_run_execution(ScheduleRunExecutionCommand(handoff_id=handoff_id))
        return ResumeSafeCheckpointResult(
            accepted.accepted,
            accepted.reason_code,
            run.id,
            run.status.value,
            run.version,
            handoff_id,
            None if accepted.accepted else "workflow submission was not accepted",
        )

    @staticmethod
    def _guard(
        unit_of_work: UnitOfWork,
        command: ResumeSafeCheckpointCommand,
        status: RunStatusV1,
        version: int,
    ) -> tuple[str, str] | None:
        if command.expected_run_version != version:
            return "VERSION_CONFLICT", "expected_run_version does not match current version"
        if status not in _ALLOWED_SOURCE_STATUSES:
            return "RESUME_NOT_ALLOWED", "current Run status forbids generic safe resume"
        if has_durable_cancel_intent(unit_of_work.cancel_intents, command.run_id):
            return "RESUME_NOT_ALLOWED", "durable cancel intent forbids generic safe resume"
        plans = current_plan_tuple(unit_of_work.plans, command.run_id)
        plan = max(plans, key=lambda item: item.revision_no, default=None)
        actions = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)
        if any(action.status in _UNRESOLVED_WRITE_STATUSES for action in actions):
            return "RESUME_NOT_ALLOWED", "unresolved write fact forbids generic safe resume"
        return None

    @staticmethod
    def _not_allowed(run: Run, detail: str) -> ResumeSafeCheckpointResult:
        return ResumeSafeCheckpointResult(
            False,
            "RESUME_NOT_ALLOWED",
            run.id,
            run.status.value,
            run.version,
            None,
            detail,
        )


__all__ = [
    "ResumeSafeCheckpointCommand",
    "ResumeSafeCheckpointHandler",
    "ResumeSafeCheckpointResult",
]
