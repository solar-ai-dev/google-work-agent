"""Resume only a matrix-allowed same-Run safe checkpoint."""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import cast

from google_work_agent.application.use_cases.plan.persistence_projection import current_plan_tuple
from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryCommand,
    RequireRecoveryHandler,
)
from google_work_agent.application.use_cases.run.cancel_intent import has_durable_cancel_intent
from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetValidator
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.recovery.model import RecoveryReasonV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import Run, RunStatusV1
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.checkpoint_port import CheckpointPort
from google_work_agent.ports.system.contracts.checkpoint import GraphCheckpointEnvelopeV1
from google_work_agent.ports.system.contracts.operational_command_replay import (
    JsonValue,
    OperationalCommandContextV1,
)
from google_work_agent.ports.system.contracts.workflow_binding import WorkflowBindingV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
    RunExecutionRefV1,
    WorkflowHandoffStageV1,
)
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
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


def safe_checkpoint_resume_is_allowed(
    *,
    unit_of_work: UnitOfWork,
    checkpoint_port: CheckpointPort,
    run: Run,
    resume_target_registry: ResumeTargetValidator,
) -> bool:
    """Read-only eligibility projection shared with Error UI actions."""
    binding = checkpoint_port.load_workflow_binding(run.id)
    checkpoint = (
        None
        if binding is None
        else checkpoint_port.load_same_run_checkpoint(run.id, binding.langgraph_thread_id)
    )
    if ResumeSafeCheckpointHandler._checkpoint_mismatch(run, binding, checkpoint) is not None:
        return False
    assert checkpoint is not None and checkpoint.registered_resume_target is not None
    try:
        resume_target_registry.validate(checkpoint.registered_resume_target)
    except (LookupError, ValueError):
        return False
    command = ResumeSafeCheckpointCommand(
        command_id="projection-only",
        request_hash="projection-only",
        run_id=run.id,
        expected_run_version=run.version,
    )
    return (
        ResumeSafeCheckpointHandler._guard(unit_of_work, command, run.status, run.version) is None
    )


@dataclass(frozen=True, slots=True)
class ResumeSafeCheckpointCommand:
    command_id: str
    request_hash: str
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
        checkpoint_port: CheckpointPort,
        resume_target_registry: ResumeTargetValidator,
        schedule_run_execution: Callable[[ScheduleRunExecutionCommand], RunExecutionAcceptedV1],
        id_factory: Callable[[], str],
        operational_replay: OperationalCommandReplayPort,
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._checkpoint_port = checkpoint_port
        self._resume_target_registry = resume_target_registry
        self._schedule_run_execution = schedule_run_execution
        self._id_factory = id_factory
        self._operational_replay = operational_replay
        self._now_ms = now_ms

    def __call__(self, command: ResumeSafeCheckpointCommand) -> ResumeSafeCheckpointResult:
        replay_context = OperationalCommandContextV1(
            command_id=command.command_id,
            operation_kind="run.resume_safe_checkpoint",
            canonical_request_hash=command.request_hash,
        )
        replay = self._operational_replay.reserve_or_replay(replay_context)
        if replay.decision == "CONFLICT":
            return self._current_result(
                command,
                ResultCode.DUPLICATE_COMMAND.value,
                "command_id already exists with a different request_hash",
            )
        if replay.decision == "REPLAY_COMPLETED":
            if not isinstance(replay.bounded_result, dict):
                raise RuntimeError("completed safe-resume replay has no bounded result")
            return _stored_result(replay.bounded_result)

        handoff_id: str | None = None
        result_ref = replay.operation_ref or command.command_id
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(command.run_id)
            if run is None:
                raise LookupError(f"run not found: {command.run_id}")
            existing = unit_of_work.workflow_handoffs.get_by_trigger_command_id(command.command_id)
            if replay.decision == "RECOVER_RESERVED" and existing is not None:
                handoff_id = existing.handoff_id
                result_ref = handoff_id
                result = ResumeSafeCheckpointResult(
                    True,
                    ResultCode.TRANSITION_APPLIED.value,
                    run.id,
                    run.status.value,
                    run.version,
                    handoff_id,
                )
            else:
                result = self._prepare(unit_of_work, command, run)
                handoff_id = result.handoff_id
                result_ref = handoff_id or f"safe-resume:{command.command_id}"

        if handoff_id is not None:
            accepted = self._schedule_run_execution(
                ScheduleRunExecutionCommand(handoff_id=handoff_id)
            )
            result = ResumeSafeCheckpointResult(
                accepted.accepted,
                accepted.reason_code,
                result.run_id,
                result.run_status,
                result.run_version,
                handoff_id,
                None if accepted.accepted else "workflow submission was not accepted",
            )
        self._operational_replay.store_result(
            replay_context,
            result_ref,
            cast(JsonValue, asdict(result)),
        )
        return result

    def _prepare(
        self,
        unit_of_work: UnitOfWork,
        command: ResumeSafeCheckpointCommand,
        run: Run,
    ) -> ResumeSafeCheckpointResult:
        binding = self._checkpoint_port.load_workflow_binding(run.id)
        checkpoint = (
            None
            if binding is None
            else self._checkpoint_port.load_same_run_checkpoint(run.id, binding.langgraph_thread_id)
        )
        mismatch = self._checkpoint_mismatch(run, binding, checkpoint)
        if mismatch is None:
            assert checkpoint is not None and checkpoint.registered_resume_target is not None
            try:
                self._resume_target_registry.validate(checkpoint.registered_resume_target)
            except (LookupError, ValueError):
                mismatch = "registered resume target is invalid"
        recovery_command = self._recovery_command(command, checkpoint, mismatch)
        recovery_receipt = unit_of_work.command_receipts.get_by_command_id(
            recovery_command.command_id
        )
        if recovery_receipt is not None:
            recovery = RequireRecoveryHandler.apply_in_unit_of_work(
                unit_of_work,
                recovery_command,
                now_ms=self._now_ms(),
                checkpoint_port=self._checkpoint_port,
            )
            unit_of_work.commit()
            return ResumeSafeCheckpointResult(
                recovery.applied,
                recovery.result_code,
                run.id,
                recovery.current_status,
                recovery.current_version,
                None,
                recovery.conflict_detail,
            )

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
        if mismatch is not None:
            recovery = RequireRecoveryHandler.apply_in_unit_of_work(
                unit_of_work,
                recovery_command,
                now_ms=self._now_ms(),
                checkpoint_port=self._checkpoint_port,
            )
            unit_of_work.commit()
            return ResumeSafeCheckpointResult(
                recovery.applied,
                recovery.result_code,
                run.id,
                recovery.current_status,
                recovery.current_version,
                None,
                recovery.conflict_detail,
            )
        assert binding is not None and checkpoint is not None
        assert checkpoint.registered_resume_target is not None
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
        return ResumeSafeCheckpointResult(
            True,
            ResultCode.TRANSITION_APPLIED.value,
            run.id,
            run.status.value,
            run.version,
            handoff_id,
        )

    @staticmethod
    def _checkpoint_mismatch(
        run: Run,
        binding: WorkflowBindingV1 | None,
        checkpoint: GraphCheckpointEnvelopeV1 | None,
    ) -> str | None:
        if binding is None:
            return "workflow binding is unavailable"
        if (
            checkpoint is None
            or checkpoint.run_id != run.id
            or checkpoint.langgraph_thread_id != binding.langgraph_thread_id
            or checkpoint.graph_profile != binding.graph_profile
            or checkpoint.graph_version != binding.graph_version
            or checkpoint.registered_resume_target is None
        ):
            return "checkpoint binding does not match the Run"
        return None

    @staticmethod
    def _recovery_command(
        command: ResumeSafeCheckpointCommand,
        checkpoint: GraphCheckpointEnvelopeV1 | None,
        mismatch: str | None,
    ) -> RequireRecoveryCommand:
        registered_target = getattr(checkpoint, "registered_resume_target", None)
        reason: RecoveryReasonV1 = (
            "CHECKPOINT_MISMATCH" if registered_target is not None else "CONTRACT_VIOLATION"
        )
        fingerprint = calculate_canonical_json_hash(
            {
                "command_id": command.command_id,
                "run_id": command.run_id,
                "checkpoint_id": getattr(checkpoint, "checkpoint_id", None),
                "checkpoint_generation": getattr(checkpoint, "checkpoint_generation", None),
                "mismatch": mismatch,
            }
        )
        return RequireRecoveryCommand(
            run_id=command.run_id,
            expected_version=command.expected_run_version,
            command_id=f"system:safe-checkpoint-recovery:{command.command_id}",
            request_hash=fingerprint,
            reason=reason,
            scope="RUN",
            recovery_fingerprint=fingerprint,
            registered_resume_target=registered_target,
            contract_or_checkpoint_fingerprint=fingerprint,
        )

    def _current_result(
        self, command: ResumeSafeCheckpointCommand, code: str, detail: str
    ) -> ResumeSafeCheckpointResult:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(command.run_id)
        if run is None:
            raise LookupError(f"run not found: {command.run_id}")
        return ResumeSafeCheckpointResult(
            False,
            code,
            run.id,
            run.status.value,
            run.version,
            None,
            detail,
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


def _stored_result(payload: dict[str, JsonValue]) -> ResumeSafeCheckpointResult:
    applied = payload.get("applied")
    result_code = payload.get("result_code")
    run_id = payload.get("run_id")
    run_status = payload.get("run_status")
    run_version = payload.get("run_version")
    handoff_id = payload.get("handoff_id")
    conflict_detail = payload.get("conflict_detail")
    if (
        not isinstance(applied, bool)
        or not isinstance(result_code, str)
        or not isinstance(run_id, str)
        or not isinstance(run_status, str)
        or not isinstance(run_version, int)
        or isinstance(run_version, bool)
        or (handoff_id is not None and not isinstance(handoff_id, str))
        or (conflict_detail is not None and not isinstance(conflict_detail, str))
    ):
        raise RuntimeError("completed safe-resume replay result is invalid")
    return ResumeSafeCheckpointResult(
        applied,
        result_code,
        run_id,
        run_status,
        run_version,
        handoff_id,
        conflict_detail,
    )


__all__ = [
    "ResumeSafeCheckpointCommand",
    "ResumeSafeCheckpointHandler",
    "ResumeSafeCheckpointResult",
    "safe_checkpoint_resume_is_allowed",
]
