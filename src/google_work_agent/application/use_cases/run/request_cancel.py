"""Application use case for durable Run cancellation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads

from google_work_agent.application.use_cases.action.write_persistence import (
    audit_event,
)
from google_work_agent.application.use_cases.run.continue_cancel_resolution import (
    ContinueCancelResolutionCommandV1,
    ContinueCancelResolutionResultV1,
)
from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetIssuer
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.domain.command_receipt.model import (
    CommandReceipt as CommandReceiptRecord,
)
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.transitions.request_cancel import transition_request_cancel
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
    RunExecutionRefV1,
    WorkflowHandoffStageV1,
)
from google_work_agent.ports.system.uuid_port import UUIDPort


@dataclass(frozen=True, slots=True)
class RequestCancelCommand:
    run_id: str
    expected_version: int
    command_id: str
    request_hash: str


@dataclass(frozen=True, slots=True)
class RequestCancelResult:
    applied: bool
    result_code: str
    current_status: str
    current_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None
    result_kind: str | None = None


class RequestCancelHandler:
    """Own durable cancel truth and its same-UoW continuation handoff."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        id_generator: UUIDPort,
        resume_target_registry: ResumeTargetIssuer,
        schedule_run_execution: Callable[[ScheduleRunExecutionCommand], RunExecutionAcceptedV1],
        continue_cancel_resolution: Callable[
            [ContinueCancelResolutionCommandV1], ContinueCancelResolutionResultV1
        ]
        | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._id_generator = id_generator
        self._resume_target_registry = resume_target_registry
        self._schedule_run_execution = schedule_run_execution
        self._continue_cancel_resolution = continue_cancel_resolution

    def __call__(
        self, command: RequestCancelCommand, *, request_id: str | None = None
    ) -> RequestCancelResult:
        del request_id
        result = self._persist(command)
        if result.applied and result.current_status == "CANCEL_REQUESTED":
            with self._unit_of_work_factory() as unit_of_work:
                handoff = unit_of_work.workflow_handoffs.get_by_trigger_command_id(
                    command.command_id
                )
            if handoff is not None:
                self._schedule_run_execution(
                    ScheduleRunExecutionCommand(handoff_id=handoff.handoff_id)
                )
            elif self._continue_cancel_resolution is not None:
                with self._unit_of_work_factory() as unit_of_work:
                    head = unit_of_work.workflow_handoffs.get_dispatch_head(command.run_id)
                if head is None:
                    self._continue_cancel_resolution(
                        ContinueCancelResolutionCommandV1(1, command.run_id)
                    )
        return result

    def _persist(self, command: RequestCancelCommand) -> RequestCancelResult:
        with self._unit_of_work_factory() as unit_of_work:
            now_ms = self._now_ms()
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._replay(unit_of_work, command, existing)
            run = unit_of_work.runs.get(command.run_id)
            if run is None:
                raise LookupError(f"run not found: {command.run_id}")
            plans = current_plan_tuple(unit_of_work.plans, run.id)
            plan = max(plans, key=lambda item: (item.revision_no, item.created_at_ms), default=None)
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="RequestRunCancellation",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            if run.version != command.expected_version:
                result = RequestCancelResult(
                    False,
                    ResultCode.VERSION_CONFLICT.value,
                    run.status.value,
                    run.version,
                    (),
                    "expected_version does not match current_version",
                )
            else:
                requested_status = transition_request_cancel(run.status)
                if not unit_of_work.runs.update_if_version_and_status(
                    run.id,
                    run.version,
                    frozenset({run.status}),
                    {"status": requested_status.value, "version": run.version + 1},
                ):
                    raise RuntimeError("validated RequestCancel CAS failed")
            if run.version != command.expected_version:
                pass
            else:
                result = RequestCancelResult(
                    True,
                    ResultCode.TRANSITION_APPLIED.value,
                    requested_status.value,
                    run.version + 1,
                    (),
                    result_kind="CANCEL_REQUESTED",
                )
                unit_of_work.workflow_handoffs.supersede_unconsumed_for_run(
                    run.id, "CANCEL_REQUESTED"
                )
                self._stage_cancel_handoff(unit_of_work, command)
            if result.applied:
                metadata: dict[str, object] = {
                    "plan_id": None if plan is None else plan.id
                }
                unit_of_work.traces.append(
                    TraceEventRecord(
                        run_id=run.id,
                        action_id=None,
                        event_type="RUN_CANCELLATION_REQUESTED",
                        status=result.current_status,
                        duration_ms=None,
                        payload_json=dumps(metadata, sort_keys=True),
                        created_at_ms=now_ms,
                    )
                )
                unit_of_work.audits.append(
                    audit_event(
                        run_id=run.id,
                        action_id=None,
                        event_type="RUN_CANCELLATION_REQUESTED",
                        outcome=result.result_code,
                        metadata=metadata,
                        created_at_ms=now_ms,
                    )
                )
            unit_of_work.command_receipts.store_result(
                command_id=command.command_id,
                applied=result.applied,
                result_code=ResultCode(result.result_code),
                result_version=result.current_version,
                response_json=dumps(asdict(result), sort_keys=True),
                completed_at_ms=now_ms,
            )
            unit_of_work.commit()
            return result

    def _stage_cancel_handoff(
        self, unit_of_work: UnitOfWork, command: RequestCancelCommand
    ) -> None:
        binding = unit_of_work.checkpoints.load_workflow_binding(command.run_id)
        if binding is None:
            return
        checkpoint = unit_of_work.checkpoints.load_same_run_checkpoint(
            command.run_id, binding.langgraph_thread_id
        )
        if checkpoint is None:
            return
        target = self._resume_target_registry.issue_main_stage(
            binding.graph_profile, "CANCEL_RESOLUTION", binding.graph_version
        )
        unit_of_work.workflow_handoffs.stage_pending(
            WorkflowHandoffStageV1(
                schema_version=1,
                handoff_id=self._id_generator.new_uuid(),
                trigger_command_id=command.command_id,
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
                control_kind="NONE",
                control=None,
                control_payload_hash=None,
            )
        )

    @staticmethod
    def _replay(
        unit_of_work: UnitOfWork,
        command: RequestCancelCommand,
        receipt: CommandReceiptRecord,
    ) -> RequestCancelResult:
        if receipt.request_hash != command.request_hash:
            run = unit_of_work.runs.get(command.run_id)
            return RequestCancelResult(
                False,
                ResultCode.DUPLICATE_COMMAND.value,
                run.status.value if run else "UNKNOWN",
                run.version if run else 0,
                (),
                "command_id already exists with a different request_hash",
            )
        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            raise RuntimeError("RECEIVED receipt requires transaction recovery before replay")
        payload = loads(receipt.response_json)
        payload["next_allowed_commands"] = tuple(payload.get("next_allowed_commands", ()))
        return RequestCancelResult(**payload)
