"""Canonical Application lifecycle command for entering a confirmation interrupt."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from json import dumps, loads

from google_work_agent.application.use_cases.plan.persistence_projection import current_plan_tuple
from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetValidator
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.audit_event.model import AuditEvent
from google_work_agent.domain.command_receipt.model import CommandReceipt, CommandReceiptStatus
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.request_confirmation import (
    transition_request_confirmation,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.checkpoint_port import CheckpointPort
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    SemanticAgentOwnerIdV1,
)

_UNRESOLVED = frozenset(
    {
        ActionStatusV1.EXECUTING,
        ActionStatusV1.UNKNOWN_RESULT,
        ActionStatusV1.EXECUTED,
        ActionStatusV1.MISMATCH,
    }
)


@dataclass(frozen=True, slots=True)
class RequestConfirmationCommand:
    run_id: str
    expected_version: int
    interrupt_id: str
    request_hash: str
    semantic_owner_id: SemanticAgentOwnerIdV1
    resume_target: AgentNodeResumeTargetV2


@dataclass(frozen=True, slots=True)
class RequestConfirmationResult:
    applied: bool
    result_code: str
    run_id: str
    current_status: str
    current_version: int
    interrupt_id: str
    semantic_owner_id: SemanticAgentOwnerIdV1
    resume_target: AgentNodeResumeTargetV2
    pre_confirmation_status: str
    checkpoint_id: str | None
    checkpoint_generation: int | None
    conflict_detail: str | None = None


class RequestConfirmationHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        checkpoint_port: CheckpointPort,
        now_ms: Callable[[], int],
        resume_target_registry: ResumeTargetValidator,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._checkpoint_port = checkpoint_port
        self._now_ms = now_ms
        self._resume_target_registry = resume_target_registry

    def __call__(self, command: RequestConfirmationCommand) -> RequestConfirmationResult:
        self._resume_target_registry.validate(command.resume_target)
        if command.resume_target.semantic_owner_id != command.semantic_owner_id:
            raise ValueError("confirmation owner and resume target do not match")
        checkpoint_update = None
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.interrupt_id)
            if existing is not None:
                return self._replay(existing, command)
            run = unit_of_work.runs.get(command.run_id)
            if run is None:
                raise LookupError(f"run not found: {command.run_id}")
            binding = self._checkpoint_port.load_workflow_binding(command.run_id)
            if binding is None:
                raise RuntimeError("confirmation requires a durable workflow binding")
            checkpoint = self._checkpoint_port.load_same_run_checkpoint(
                command.run_id, binding.langgraph_thread_id
            )
            if checkpoint is None:
                raise RuntimeError("confirmation requires a durable runnable checkpoint")
            if (
                command.resume_target.graph_profile != binding.graph_profile
                or command.resume_target.graph_version != binding.graph_version
            ):
                raise ValueError("confirmation target does not match the workflow binding")

            now_ms = self._now_ms()
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.interrupt_id,
                command_type="RequestConfirmation",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            review_disposition, unresolved = _published_review_facts(unit_of_work, command.run_id)
            try:
                next_status = transition_request_confirmation(
                    run.status,
                    durable_review_disposition=review_disposition,
                    unresolved_external_effect_count=unresolved,
                )
            except RunTransitionRejected as error:
                result = _result(
                    command,
                    False,
                    ResultCode.STATE_CONFLICT,
                    run.status,
                    run.version,
                    run.status,
                    None,
                    None,
                    str(error),
                )
            else:
                applied = unit_of_work.runs.update_if_version_and_status(
                    command.run_id,
                    command.expected_version,
                    frozenset({run.status}),
                    {"status": next_status.value, "version": run.version + 1},
                )
                if not applied:
                    current = unit_of_work.runs.get(command.run_id)
                    if current is None:
                        raise LookupError(f"run not found: {command.run_id}")
                    result = _result(
                        command,
                        False,
                        ResultCode.VERSION_CONFLICT,
                        current.status,
                        current.version,
                        run.status,
                        None,
                        None,
                        "version mismatch or compare-and-set conflict",
                    )
                else:
                    checkpoint_update = replace(
                        checkpoint,
                        owner_scope=command.semantic_owner_id,
                        registered_resume_target=command.resume_target,
                        created_at_ms=now_ms,
                    )
                    result = _result(
                        command,
                        True,
                        ResultCode.TRANSITION_APPLIED,
                        next_status,
                        run.version + 1,
                        run.status,
                        checkpoint.checkpoint_id,
                        checkpoint.checkpoint_generation,
                    )
                    unit_of_work.audits.append(_audit(command, result, now_ms))
            unit_of_work.command_receipts.store_result(
                command_id=command.interrupt_id,
                applied=result.applied,
                result_code=ResultCode(result.result_code),
                result_version=result.current_version,
                response_json=dumps(asdict(result), sort_keys=True),
                completed_at_ms=now_ms,
            )
            unit_of_work.commit()
        if checkpoint_update is not None:
            self._checkpoint_port.store_same_run_checkpoint(checkpoint_update)
        return result

    @staticmethod
    def _replay(
        receipt: CommandReceipt, command: RequestConfirmationCommand
    ) -> RequestConfirmationResult:
        if receipt.request_hash != command.request_hash:
            raise ValueError("interrupt_id already identifies a different confirmation request")
        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            raise RuntimeError("RECEIVED RequestConfirmation requires transaction recovery")
        payload = loads(receipt.response_json)
        payload["resume_target"] = AgentNodeResumeTargetV2(**payload["resume_target"])
        return RequestConfirmationResult(**payload)


def _published_review_facts(unit_of_work: UnitOfWork, run_id: str) -> tuple[str | None, int]:
    plans = current_plan_tuple(unit_of_work.plans, run_id)
    plan = max(plans, key=lambda item: (item.revision_no, item.created_at_ms), default=None)
    if plan is None:
        return None, 0
    actions = unit_of_work.actions.list_for_plan(plan.id)
    unresolved = sum(1 for action in actions if ActionStatusV1(action.status) in _UNRESOLVED)
    return plan.review_disposition, unresolved


def _result(
    command: RequestConfirmationCommand,
    applied: bool,
    result_code: ResultCode,
    status: RunStatusV1,
    version: int,
    pre_status: RunStatusV1,
    checkpoint_id: str | None,
    checkpoint_generation: int | None,
    conflict_detail: str | None = None,
) -> RequestConfirmationResult:
    return RequestConfirmationResult(
        applied=applied,
        result_code=result_code.value,
        run_id=command.run_id,
        current_status=status.value,
        current_version=version,
        interrupt_id=command.interrupt_id,
        semantic_owner_id=command.semantic_owner_id,
        resume_target=command.resume_target,
        pre_confirmation_status=pre_status.value,
        checkpoint_id=checkpoint_id,
        checkpoint_generation=checkpoint_generation,
        conflict_detail=conflict_detail,
    )


def _audit(
    command: RequestConfirmationCommand,
    result: RequestConfirmationResult,
    now_ms: int,
) -> AuditEvent:
    from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord

    return AuditEventRecord(
        account_id=None,
        run_id=command.run_id,
        action_id=None,
        actor_type="SYSTEM",
        actor_id="run_lifecycle",
        actor_display="Run lifecycle",
        event_type="CONFIRMATION_REQUESTED",
        outcome=result.result_code,
        metadata_json=dumps(
            {
                "interrupt_id": command.interrupt_id,
                "semantic_owner_id": command.semantic_owner_id,
                "resume_target": asdict(command.resume_target),
                "pre_confirmation_status": result.pre_confirmation_status,
            },
            sort_keys=True,
        ),
        created_at_ms=now_ms,
    )


__all__ = [
    "RequestConfirmationCommand",
    "RequestConfirmationHandler",
    "RequestConfirmationResult",
]
