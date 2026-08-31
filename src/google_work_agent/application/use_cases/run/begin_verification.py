"""Canonical persisted BeginVerification application boundary."""

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from json import dumps, loads

from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetIssuer
from google_work_agent.domain.audit_event.model import AuditEvent
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import Run, RunCommand, RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.begin_verification import (
    transition_begin_verification,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.checkpoint_port import CheckpointPort


@dataclass(frozen=True, slots=True)
class BeginVerificationCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_version: int | None = None


@dataclass(frozen=True, slots=True)
class BeginVerificationResult:
    applied: bool
    result_code: ResultCode
    current_status: RunStatusV1
    current_version: int
    next_allowed_commands: tuple[RunCommand, ...] = ()
    conflict_detail: str | None = None


class BeginVerificationHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        checkpoint_port: CheckpointPort,
        now_ms: Callable[[], int],
        resume_target_registry: ResumeTargetIssuer,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._checkpoint_port = checkpoint_port
        self._now_ms = now_ms
        self._resume_target_registry = resume_target_registry

    def __call__(self, command: BeginVerificationCommand) -> BeginVerificationResult:
        checkpoint_update = None
        with self._unit_of_work_factory() as unit_of_work:
            now_ms = self._now_ms()
            receipt = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if receipt is not None:
                if receipt.request_hash != command.request_hash:
                    run = _require_run(unit_of_work, command.run_id)
                    return BeginVerificationResult(
                        False,
                        ResultCode.DUPLICATE_COMMAND,
                        run.status,
                        run.version,
                        conflict_detail="command_id exists with a different request_hash",
                    )
                if (
                    receipt.response_json is not None
                    and receipt.status is not CommandReceiptStatus.RECEIVED
                ):
                    payload = loads(receipt.response_json)
                    return BeginVerificationResult(
                        applied=bool(payload["applied"]),
                        result_code=ResultCode(payload["result_code"]),
                        current_status=RunStatusV1(payload["current_status"]),
                        current_version=int(payload["current_version"]),
                        conflict_detail=payload.get("conflict_detail"),
                    )
                raise RuntimeError("RECEIVED BeginVerification receipt requires reconciliation")

            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="BeginVerification",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            run = _require_run(unit_of_work, command.run_id)
            if command.expected_version is not None and run.version != command.expected_version:
                result = BeginVerificationResult(
                    False,
                    ResultCode.VERSION_CONFLICT,
                    run.status,
                    run.version,
                    conflict_detail="expected_version does not match current_version",
                )
            else:
                try:
                    next_status = transition_begin_verification(run.status)
                except RunTransitionRejected as error:
                    result = BeginVerificationResult(
                        False,
                        ResultCode.STATE_CONFLICT,
                        run.status,
                        run.version,
                        conflict_detail=str(error),
                    )
                else:
                    if not unit_of_work.runs.update_if_version_and_status(
                        run.id,
                        run.version,
                        frozenset({run.status}),
                        {"status": next_status.value, "version": run.version + 1},
                    ):
                        raise RuntimeError("validated BeginVerification CAS failed")
                    binding = self._checkpoint_port.load_workflow_binding(run.id)
                    checkpoint = (
                        None
                        if binding is None
                        else self._checkpoint_port.load_same_run_checkpoint(
                            run.id, binding.langgraph_thread_id
                        )
                    )
                    if binding is None or checkpoint is None:
                        raise RuntimeError(
                            "BeginVerification requires a current workflow checkpoint"
                        )
                    verification_target = self._resume_target_registry.issue_main_stage(
                        binding.graph_profile,
                        "VERIFICATION",
                        binding.graph_version,
                    )
                    checkpoint_update = replace(
                        checkpoint,
                        registered_resume_target=verification_target,
                        created_at_ms=now_ms,
                    )
                    unit_of_work.audits.append(
                        AuditEvent(
                            account_id=None,
                            run_id=run.id,
                            action_id=None,
                            actor_type="AGENT",
                            actor_id="begin_verification",
                            actor_display="BeginVerification",
                            event_type="RUN_VERIFICATION_STARTED",
                            outcome=ResultCode.TRANSITION_APPLIED.value,
                            metadata_json=dumps({"command_id": command.command_id}, sort_keys=True),
                            created_at_ms=now_ms,
                        )
                    )
                    result = BeginVerificationResult(
                        True,
                        ResultCode.TRANSITION_APPLIED,
                        next_status,
                        run.version + 1,
                    )
            payload = asdict(result)
            payload["result_code"] = result.result_code.value
            payload["current_status"] = result.current_status.value
            unit_of_work.command_receipts.store_result(
                command_id=command.command_id,
                applied=result.applied,
                result_code=result.result_code,
                result_version=result.current_version,
                response_json=dumps(payload, sort_keys=True),
                completed_at_ms=now_ms,
            )
            unit_of_work.commit()
        if checkpoint_update is not None:
            self._checkpoint_port.store_same_run_checkpoint(checkpoint_update)
        return result


def _require_run(unit_of_work: UnitOfWork, run_id: str) -> Run:
    run = unit_of_work.runs.get(run_id)
    if run is None:
        raise LookupError(f"run not found: {run_id}")
    return run


__all__ = ["BeginVerificationCommand", "BeginVerificationHandler", "BeginVerificationResult"]
