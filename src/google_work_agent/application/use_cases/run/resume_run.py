"""Resume one persisted run through the canonical Domain authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from json import dumps
from typing import cast

from google_work_agent.application.cancel_intent import has_durable_cancel_intent
from google_work_agent.application.run_command_receipts import (
    finish_json_receipt,
    resolve_existing_receipt,
)
from google_work_agent.application.use_cases.recovery.resolve_recovery import (
    ResolveRecoveryHandler,
)
from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetValidator
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import UUIDPort
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
    RunExecutionRefV1,
    WorkflowHandoffStageV1,
)

ResumeAuthority = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ResumeRunCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_run_version: int
    resume_kind: str
    api_contract_version: str


@dataclass(frozen=True, slots=True)
class ResumeRunResult:
    applied: bool
    result_code: str
    run_id: str
    run_status: str
    run_version: int
    should_enqueue: bool
    request_replayed: bool
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class _PersistedRunDecision:
    applied: bool
    result_code: ResultCode
    current_status: RunStatusV1
    current_version: int
    conflict_detail: str | None


_REAUTH_DISPATCH_UNCERTAIN_ACTION_STATUSES = frozenset(
    {
        ActionStatusV1.EXECUTING.value,
        ActionStatusV1.UNKNOWN_RESULT.value,
        ActionStatusV1.EXECUTED.value,
    }
)


class ResumeRunHandler:
    """Own receipt, persisted resume transition, observability, commit, and handoff."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        resolve_resume_authority: Callable[..., ResumeAuthority | None],
        id_generator: UUIDPort,
        resume_target_registry: ResumeTargetValidator,
        schedule_run_execution: Callable[[ScheduleRunExecutionCommand], RunExecutionAcceptedV1],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._resolve_resume_authority = resolve_resume_authority
        self._id_generator = id_generator
        self._resume_target_registry = resume_target_registry
        self._schedule_run_execution = schedule_run_execution

    def __call__(
        self,
        command: ResumeRunCommand,
        *,
        request_id: str,
        resume_payload: dict[str, object] | None = None,
    ) -> ResumeRunResult:
        payload = {} if resume_payload is None else dict(resume_payload)
        authority = None
        if command.resume_kind == "REAUTH_COMPLETED":
            authority = self._resolve_resume_authority(
                run_id=command.run_id, resume_kind=command.resume_kind
            )
        result = self._persist(command, authority=authority, resume_payload=payload)
        del request_id
        if result.applied and result.should_enqueue:
            with self._unit_of_work_factory() as unit_of_work:
                handoff = unit_of_work.workflow_handoffs.get_by_trigger_command_id(
                    command.command_id
                )
            if handoff is not None:
                self._schedule_run_execution(
                    ScheduleRunExecutionCommand(handoff_id=handoff.handoff_id)
                )
        return result

    def _persist(
        self,
        command: ResumeRunCommand,
        *,
        authority: ResumeAuthority | None,
        resume_payload: dict[str, object],
    ) -> ResumeRunResult:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                response = cast(
                    ResumeRunResult,
                    resolve_existing_receipt(
                        unit_of_work=unit_of_work,
                        receipt=existing,
                        request_hash=command.request_hash,
                        response_type=ResumeRunResult,
                        run_id=command.run_id,
                        now_ms=self._now_ms(),
                    ),
                )
                return ResumeRunResult(
                    **{**asdict(response), "should_enqueue": False, "request_replayed": True}
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="ResumeRun",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            run = unit_of_work.runs.get(command.run_id)
            if run is None:
                raise LookupError(f"run not found: {command.run_id}")
            plans = current_plan_tuple(unit_of_work.plans, command.run_id)
            latest_plan = max(
                plans, key=lambda item: (item.revision_no, item.created_at_ms), default=None
            )
            actions = (
                () if latest_plan is None else unit_of_work.actions.list_for_plan(latest_plan.id)
            )
            unknown_result_exists = any(
                action.status == ActionStatusV1.UNKNOWN_RESULT.value for action in actions
            )
            reauth_dispatch_uncertain = any(
                action.status in _REAUTH_DISPATCH_UNCERTAIN_ACTION_STATUSES for action in actions
            )

            response = self._validate(
                command, run, unknown_result_exists, authority, resume_payload
            )
            if response is None:
                decision, should_enqueue = self._apply_canonical_transition(
                    unit_of_work,
                    command,
                    run.version,
                    authority,
                    reauth_dispatch_uncertain=reauth_dispatch_uncertain,
                    now_ms=now_ms,
                )
                response = ResumeRunResult(
                    applied=decision.applied,
                    result_code=decision.result_code.value,
                    run_id=run.id,
                    run_status=decision.current_status.value,
                    run_version=decision.current_version,
                    should_enqueue=should_enqueue,
                    request_replayed=False,
                    conflict_detail=decision.conflict_detail,
                )
            if response.applied:
                metadata = {"command_id": command.command_id, "resume_kind": command.resume_kind}
                event_type = (
                    "RUN_REAUTH_RESUMED"
                    if command.resume_kind == "REAUTH_COMPLETED"
                    else "RUN_RESUMED"
                )
                unit_of_work.traces.append(
                    TraceEventRecord(
                        run_id=run.id,
                        action_id=None,
                        event_type=event_type,
                        status=response.run_status,
                        duration_ms=None,
                        payload_json=dumps(metadata, sort_keys=True),
                        created_at_ms=now_ms,
                    )
                )
                unit_of_work.audits.append(
                    AuditEventRecord(
                        account_id=None,
                        run_id=run.id,
                        action_id=None,
                        actor_type="USER",
                        actor_id="local_user",
                        actor_display=None,
                        event_type=event_type,
                        outcome=response.result_code,
                        metadata_json=dumps(metadata, sort_keys=True),
                        created_at_ms=now_ms,
                    )
                )
                if response.should_enqueue:
                    self._stage_resume_handoff(unit_of_work, command)
            finish_json_receipt(
                unit_of_work, command.command_id, response, response.run_version, now_ms
            )
            unit_of_work.commit()
            return response

    def _stage_resume_handoff(self, unit_of_work: UnitOfWork, command: ResumeRunCommand) -> None:
        binding = unit_of_work.checkpoints.load_workflow_binding(command.run_id)
        if binding is None:
            raise RuntimeError("resume requires a durable workflow binding")
        checkpoint = unit_of_work.checkpoints.load_same_run_checkpoint(
            command.run_id, binding.langgraph_thread_id
        )
        if checkpoint is None or checkpoint.registered_resume_target is None:
            raise RuntimeError("resume requires a registered durable checkpoint target")
        self._resume_target_registry.validate(checkpoint.registered_resume_target)
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
                    resume_target=checkpoint.registered_resume_target,
                ),
                checkpoint_id=checkpoint.checkpoint_id,
                checkpoint_generation=checkpoint.checkpoint_generation,
                control_kind="NONE",
                control=None,
                control_payload_hash=None,
            )
        )

    @staticmethod
    def _validate(
        command: ResumeRunCommand,
        run: object,
        unknown_result_exists: bool,
        authority: ResumeAuthority | None,
        resume_payload: dict[str, object],
    ) -> ResumeRunResult | None:
        status = run.status  # type: ignore[attr-defined]
        version = run.version  # type: ignore[attr-defined]
        if command.expected_run_version != version:
            return ResumeRunResult(
                False,
                ResultCode.VERSION_CONFLICT.value,
                command.run_id,
                status.value,
                version,
                False,
                False,
                "expected_run_version does not match current version",
            )
        allowed = {
            "REAUTH_COMPLETED": RunStatusV1.REAUTH_REQUIRED,
            "RECOVERY_RECHECK": RunStatusV1.RECOVERY_REQUIRED,
        }
        if allowed.get(command.resume_kind) is not status:
            return ResumeRunResult(
                False,
                ResultCode.STATE_CONFLICT.value,
                command.run_id,
                status.value,
                version,
                False,
                False,
                "run status does not allow manual resume",
            )
        if unknown_result_exists and command.resume_kind not in {
            "RECOVERY_RECHECK",
            "REAUTH_COMPLETED",
        }:
            return ResumeRunResult(
                False,
                ResultCode.RECOVERY_REQUIRED.value,
                command.run_id,
                status.value,
                version,
                False,
                False,
                "unknown write results must be resolved before resume",
            )
        if command.resume_kind == "REAUTH_COMPLETED" and (
            authority is None or not isinstance(authority.get("resume_status"), str)
        ):
            return ResumeRunResult(
                False,
                ResultCode.STATE_CONFLICT.value,
                command.run_id,
                status.value,
                version,
                False,
                False,
                "persisted resume authority is unavailable",
            )
        if command.resume_kind == "REAUTH_COMPLETED":
            assert authority is not None
            try:
                resume_status = RunStatusV1(cast(str, authority["resume_status"]))
            except ValueError:
                return ResumeRunResult(
                    False,
                    ResultCode.STATE_CONFLICT.value,
                    command.run_id,
                    status.value,
                    version,
                    False,
                    False,
                    "persisted reauth resume status is invalid",
                )
            if resume_status is not RunStatusV1.RECOVERY_REQUIRED and not isinstance(
                authority.get("continuation_target"), str
            ):
                return ResumeRunResult(
                    False,
                    ResultCode.STATE_CONFLICT.value,
                    command.run_id,
                    status.value,
                    version,
                    False,
                    False,
                    "persisted reauth continuation target is unavailable",
                )
        return None

    def _apply_canonical_transition(
        self,
        unit_of_work: UnitOfWork,
        command: ResumeRunCommand,
        current_version: int,
        authority: ResumeAuthority | None,
        *,
        reauth_dispatch_uncertain: bool,
        now_ms: int,
    ):
        del authority, reauth_dispatch_uncertain, now_ms
        if command.resume_kind == "RECOVERY_RECHECK":
            decision = ResolveRecoveryHandler.recheck_in_unit_of_work(
                unit_of_work,
                run_id=command.run_id,
                expected_version=current_version,
            )
            return decision, decision.applied
        raise AssertionError(
            f"unvalidated resume kind reached transition authority: {command.resume_kind}"
        )


def _has_cancel_intent(unit_of_work: UnitOfWork, run_id: str) -> bool:
    return has_durable_cancel_intent(unit_of_work.cancel_intents, run_id)


__all__ = ["ResumeRunCommand", "ResumeRunHandler", "ResumeRunResult"]
