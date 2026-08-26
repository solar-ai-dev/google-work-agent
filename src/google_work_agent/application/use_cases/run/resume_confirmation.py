"""Canonical Application lifecycle command for resuming a confirmation."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads
from typing import Protocol, cast

from google_work_agent.application.orchestration.contracts import (
    ConfirmationResponseProjectionV1,
    PolicyConfirmationReceiptV1,
)
from google_work_agent.domain import ResultCode, RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected
from google_work_agent.domain.run.transitions.resume_confirmation import (
    transition_resume_confirmation,
)
from google_work_agent.ports.models import (
    AuditEventRecord,
    CommandReceiptRecord,
    CommandReceiptStatus,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_binding import GraphProfileIdV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    ConfirmationResumeControlV1,
    MainControlResumeTargetV2,
    MainResumeStageIdV1,
    RegisteredResumeTargetRefV2,
    RunExecutionRefV1,
    WorkflowHandoffStageV1,
)


class ResumeTargetValidator(Protocol):
    """Single canonical resume-target legality authority (ResumeTargetRegistry).

    Declared against the full RegisteredResumeTargetRefV2 union (AGENT_NODE |
    MAIN_CONTROL) so every caller needing target-legality validation --
    Confirmation resume (AgentNodeResumeTargetV2 only) and crash-recovery
    checkpoint binding (either kind) -- shares this one Protocol instead of
    each declaring its own narrower duplicate.
    """

    def validate(self, ref: RegisteredResumeTargetRefV2) -> None: ...


class ResumeTargetIssuer(ResumeTargetValidator, Protocol):
    """Issue registered targets without duplicating registry-owned target tables."""

    def issue_main_stage(
        self,
        graph_profile: GraphProfileIdV1,
        stage_id: MainResumeStageIdV1,
        graph_version: str,
    ) -> MainControlResumeTargetV2: ...


@dataclass(frozen=True, slots=True)
class ResumeConfirmationCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_version: int
    interrupt_id: str
    pre_confirmation_status: str
    resume_target: AgentNodeResumeTargetV2
    checkpoint_id: str
    checkpoint_generation: int
    confirmation_response: ConfirmationResponseProjectionV1
    policy_confirmation_receipt: PolicyConfirmationReceiptV1 | None = None


@dataclass(frozen=True, slots=True)
class ResumeConfirmationResult:
    applied: bool
    result_code: str
    run_id: str
    current_status: str
    current_version: int
    handoff_id: str | None
    request_replayed: bool
    conflict_detail: str | None = None


class ResumeConfirmationHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        id_factory: Callable[[], str],
        resume_target_registry: ResumeTargetValidator,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._id_factory = id_factory
        self._resume_target_registry = resume_target_registry

    def __call__(self, command: ResumeConfirmationCommand) -> ResumeConfirmationResult:
        self._resume_target_registry.validate(command.resume_target)
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._replay(unit_of_work, existing, command)
            run = unit_of_work.runs.get(command.run_id)
            if run is None:
                raise LookupError(f"run not found: {command.run_id}")
            binding = unit_of_work.checkpoints.load_workflow_binding(command.run_id)
            checkpoint = (
                None
                if binding is None
                else unit_of_work.checkpoints.load_same_run_checkpoint(
                    command.run_id, binding.langgraph_thread_id
                )
            )
            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="ResumeConfirmation",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            conflict = _binding_conflict(command, binding, checkpoint)
            if command.expected_version != run.version:
                result = _result(
                    command,
                    False,
                    ResultCode.VERSION_CONFLICT,
                    run.status,
                    run.version,
                    None,
                    "expected_version does not match current version",
                )
            elif conflict is not None:
                result = _result(
                    command,
                    False,
                    ResultCode.STATE_CONFLICT,
                    run.status,
                    run.version,
                    None,
                    conflict,
                )
            else:
                result = self._apply(unit_of_work, command, run.status, run.version, now_ms)
            unit_of_work.command_receipts.finish_json(
                command_id=command.command_id,
                applied=result.applied,
                result_code=ResultCode(result.result_code),
                result_version=result.current_version,
                response_json=dumps(asdict(result), sort_keys=True),
                completed_at_ms=now_ms,
            )
            unit_of_work.commit()
            return result

    def _apply(
        self,
        unit_of_work: UnitOfWork,
        command: ResumeConfirmationCommand,
        status: RunStatus,
        version: int,
        now_ms: int,
    ) -> ResumeConfirmationResult:
        try:
            resume_status = RunStatus(command.pre_confirmation_status)
            next_status = transition_resume_confirmation(status, resume_status=resume_status)
        except (ValueError, RunTransitionRejected) as error:
            return _result(
                command,
                False,
                ResultCode.STATE_CONFLICT,
                status,
                version,
                None,
                str(error),
            )
        applied = unit_of_work.runs.update_if_version_and_status(
            command.run_id,
            command.expected_version,
            frozenset({RunStatus.WAITING_CONFIRMATION}),
            {"status": next_status.value, "version": version + 1},
        )
        if not applied:
            current = unit_of_work.runs.get(command.run_id)
            if current is None:
                raise LookupError(f"run not found: {command.run_id}")
            return _result(
                command,
                False,
                ResultCode.VERSION_CONFLICT,
                current.status,
                current.version,
                None,
                "compare-and-set rejected ResumeConfirmation",
            )
        binding = unit_of_work.checkpoints.load_workflow_binding(command.run_id)
        if binding is None:
            raise RuntimeError("validated confirmation binding disappeared")
        handoff_id = self._id_factory()
        control = ConfirmationResumeControlV1(
            kind="CONFIRMATION_RESPONSE",
            confirmation_response=cast(dict[str, object], dict(command.confirmation_response)),
            policy_confirmation_receipt=(
                None
                if command.policy_confirmation_receipt is None
                else cast(dict[str, object], dict(command.policy_confirmation_receipt))
            ),
        )
        control_json = dumps(asdict(control), sort_keys=True, separators=(",", ":"))
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
                    resume_target=command.resume_target,
                ),
                checkpoint_id=command.checkpoint_id,
                checkpoint_generation=command.checkpoint_generation,
                control_kind="CONFIRMATION_RESPONSE",
                control=control,
                control_payload_hash=hashlib.sha256(control_json.encode()).hexdigest(),
            )
        )
        result = _result(
            command,
            True,
            ResultCode.TRANSITION_APPLIED,
            next_status,
            version + 1,
            handoff_id,
        )
        unit_of_work.audits.add(_audit(command, result, now_ms))
        if command.policy_confirmation_receipt is not None:
            unit_of_work.audits.add(_policy_audit(command, now_ms))
        return result

    @staticmethod
    def _replay(
        unit_of_work: UnitOfWork,
        receipt: CommandReceiptRecord,
        command: ResumeConfirmationCommand,
    ) -> ResumeConfirmationResult:
        if receipt.request_hash != command.request_hash:
            run = unit_of_work.runs.get(command.run_id)
            status = RunStatus.CREATED if run is None else run.status
            version = 0 if run is None else run.version
            return _result(
                command,
                False,
                ResultCode.DUPLICATE_COMMAND,
                status,
                version,
                None,
                "command_id already exists with a different request_hash",
            )
        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            raise RuntimeError("RECEIVED ResumeConfirmation requires transaction recovery")
        payload = loads(receipt.response_json)
        payload["request_replayed"] = True
        payload["handoff_id"] = None
        return ResumeConfirmationResult(**payload)


def _binding_conflict(command: ResumeConfirmationCommand, binding: object, checkpoint: object):
    if binding is None or checkpoint is None:
        return "durable workflow binding/checkpoint is unavailable"
    if (
        checkpoint.checkpoint_id != command.checkpoint_id
        or checkpoint.checkpoint_generation != command.checkpoint_generation
        or checkpoint.registered_resume_target != command.resume_target
    ):
        return "confirmation checkpoint authority is stale or mismatched"
    if (
        command.resume_target.graph_profile != binding.graph_profile
        or command.resume_target.graph_version != binding.graph_version
    ):
        return "confirmation target does not match workflow binding"
    return None


def _result(
    command: ResumeConfirmationCommand,
    applied: bool,
    code: ResultCode,
    status: RunStatus,
    version: int,
    handoff_id: str | None,
    detail: str | None = None,
) -> ResumeConfirmationResult:
    return ResumeConfirmationResult(
        applied=applied,
        result_code=code.value,
        run_id=command.run_id,
        current_status=status.value,
        current_version=version,
        handoff_id=handoff_id,
        request_replayed=False,
        conflict_detail=detail,
    )


def _audit(
    command: ResumeConfirmationCommand,
    result: ResumeConfirmationResult,
    now_ms: int,
) -> AuditEventRecord:
    return AuditEventRecord(
        account_id=None,
        run_id=command.run_id,
        action_id=None,
        actor_type="USER",
        actor_id="local_user",
        actor_display=None,
        event_type="CONFIRMATION_RESUMED",
        outcome=result.result_code,
        metadata_json=dumps(
            {
                "command_id": command.command_id,
                "interrupt_id": command.interrupt_id,
                "handoff_id": result.handoff_id,
                "resume_target": asdict(command.resume_target),
            },
            sort_keys=True,
        ),
        created_at_ms=now_ms,
    )


def _policy_audit(command: ResumeConfirmationCommand, now_ms: int) -> AuditEventRecord:
    receipt = command.policy_confirmation_receipt
    if receipt is None:
        raise AssertionError("policy receipt is required")
    return AuditEventRecord(
        account_id=None,
        run_id=command.run_id,
        action_id=None,
        actor_type="USER",
        actor_id="local_user",
        actor_display=None,
        event_type="POLICY_CONFIRMATION_RECORDED",
        outcome=receipt["decision"],
        metadata_json=dumps(
            {
                "confirmation_receipt_id": receipt["meta"]["artifact_id"],
                "interrupt_id": receipt["interrupt_id"],
                "confirmation_kind": receipt["confirmation_kind"],
                "decision": receipt["decision"],
                "decision_context_hash": receipt["decision_context_hash"],
                "affected_route_ids": receipt["affected_route_ids"],
                "affected_resource_refs": receipt["affected_resource_refs"],
            },
            sort_keys=True,
        ),
        created_at_ms=now_ms,
    )


__all__ = [
    "ResumeConfirmationCommand",
    "ResumeConfirmationHandler",
    "ResumeConfirmationResult",
]
