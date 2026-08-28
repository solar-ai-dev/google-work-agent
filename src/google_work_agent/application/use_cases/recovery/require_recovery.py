"""Application use case for require recovery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads
from typing import Literal, cast

from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.recovery.model import RecoveryReasonV1
from google_work_agent.domain.recovery.transitions.require_recovery import (
    transition_require_recovery,
)
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunTransitionRejected, next_allowed_run_commands
from google_work_agent.ports.persistence.recovery_repository import RecoveryContextV1
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import RegisteredResumeTargetRefV2


@dataclass(frozen=True, slots=True)
class RequireRecoveryCommand:
    run_id: str
    expected_version: int
    command_id: str
    request_hash: str
    reason: RecoveryReasonV1
    scope: Literal["RUN", "ACTION"]
    recovery_fingerprint: str
    action_id: str | None = None
    execution_attempt_id: str | None = None
    verification_id: str | None = None
    registered_resume_target: RegisteredResumeTargetRefV2 | None = None
    observed_external_state_fingerprint: str | None = None
    verification_input_fingerprint: str | None = None
    contract_or_checkpoint_fingerprint: str | None = None
    last_recheck_input_hash: str | None = None


@dataclass(frozen=True, slots=True)
class RequireRecoveryResult:
    applied: bool
    result_code: str
    current_status: str
    current_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None


class RequireRecoveryHandler:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._f = unit_of_work_factory
        self._n = now_ms

    def __call__(self, command: RequireRecoveryCommand) -> RequireRecoveryResult:
        with self._f() as u:
            r = self.apply_in_unit_of_work(u, command, now_ms=self._n())
            u.commit()
            return r

    @staticmethod
    def apply_in_unit_of_work(
        unit_of_work: UnitOfWork, command: RequireRecoveryCommand, *, now_ms: int
    ) -> RequireRecoveryResult:
        """Canonical RequireRecovery semantic writer for an enclosing short UoW.

        Resume/reauth orchestration may compose this method but never calls the
        Run repository or RecoveryContext repository directly.
        """
        existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
        if existing:
            if existing.request_hash != command.request_hash:
                run = unit_of_work.runs.get(command.run_id)
                return RequireRecoveryResult(
                    False,
                    ResultCode.DUPLICATE_COMMAND.value,
                    run.status.value if run else "UNKNOWN",
                    run.version if run else 0,
                    (),
                    "command_id already exists with a different request_hash",
                )
            if existing.status is CommandReceiptStatus.RECEIVED or existing.response_json is None:
                raise RuntimeError("RECEIVED receipt requires transaction recovery before replay")
            payload = loads(existing.response_json)
            payload["next_allowed_commands"] = tuple(payload.get("next_allowed_commands", ()))
            return RequireRecoveryResult(**payload)

        run = unit_of_work.runs.get(command.run_id)
        pre_recovery_status = run.status.value if run else "UNKNOWN"
        unit_of_work.command_receipts.reserve_or_replay(
            command_id=command.command_id,
            command_type="RequireRecovery",
            request_hash=command.request_hash,
            aggregate_type="Run",
            aggregate_id=command.run_id,
            created_at_ms=now_ms,
        )
        if run is None:
            raise LookupError(f"run not found: {command.run_id}")
        if run.version != command.expected_version:
            applied = False
            result_code = ResultCode.VERSION_CONFLICT
            next_status = run.status
            next_version = run.version
            conflict_detail = "expected_version does not match current_version"
        else:
            try:
                next_status = transition_require_recovery(run.status)
                applied = unit_of_work.runs.update_if_version_and_status(
                    run.id,
                    run.version,
                    frozenset({run.status}),
                    {"status": next_status.value, "version": run.version + 1},
                )
                result_code = (
                    ResultCode.TRANSITION_APPLIED if applied else ResultCode.VERSION_CONFLICT
                )
                next_version = run.version + 1 if applied else run.version
                conflict_detail = None if applied else "validated Run CAS failed"
            except RunTransitionRejected as error:
                applied = False
                result_code = ResultCode.STATE_CONFLICT
                next_status = run.status
                next_version = run.version
                conflict_detail = str(error)
        result = RequireRecoveryResult(
            applied,
            result_code.value,
            next_status.value,
            next_version,
            tuple(item.value for item in next_allowed_run_commands(next_status)),
            conflict_detail,
        )
        if result.applied:
            current = unit_of_work.recovery_contexts.load_current_context(command.run_id)
            context = build_recovery_context(
                command,
                pre_recovery_status=pre_recovery_status,
                version=0 if current is None else current["version"] + 1,
                now_ms=now_ms,
            )
            unit_of_work.recovery_contexts.store_context(context)
            unit_of_work.audits.append(
                build_recovery_required_audit_event(command, result.result_code, now_ms)
            )
        unit_of_work.command_receipts.store_result(
            command_id=command.command_id,
            applied=result.applied,
            result_code=result_code,
            result_version=result.current_version,
            response_json=dumps(asdict(result), sort_keys=True),
            completed_at_ms=now_ms,
        )
        return result


def build_recovery_context(
    command: RequireRecoveryCommand,
    *,
    pre_recovery_status: str,
    version: int,
    now_ms: int,
) -> RecoveryContextV1:
    """Build the closed RecoveryContextV1 record from a RequireRecoveryCommand.

    Pure (no I/O) -- shared by every atomic writer that must persist a durable
    RequireRecovery outcome inside its own single transaction (this handler,
    and ``ResumeAfterReauthHandler``'s dispatch-uncertain fail-safe).
    ``RecoveryRepository.store_context`` remains the sole write authority.
    """
    context: dict[str, object] = {
        "schema_version": 1,
        "run_id": command.run_id,
        "reason": command.reason,
        "scope": command.scope,
        "pre_recovery_status": pre_recovery_status,
        "recovery_fingerprint": command.recovery_fingerprint,
        "version": version,
        "created_at_ms": now_ms,
        "updated_at_ms": now_ms,
    }
    if command.action_id is not None:
        context["action_id"] = command.action_id
    if command.execution_attempt_id is not None:
        context["execution_attempt_id"] = command.execution_attempt_id
    if command.verification_id is not None:
        context["verification_id"] = command.verification_id
    if command.registered_resume_target is not None:
        context["registered_resume_target"] = command.registered_resume_target
    if command.observed_external_state_fingerprint is not None:
        context["observed_external_state_fingerprint"] = command.observed_external_state_fingerprint
    if command.verification_input_fingerprint is not None:
        context["verification_input_fingerprint"] = command.verification_input_fingerprint
    if command.contract_or_checkpoint_fingerprint is not None:
        context["contract_or_checkpoint_fingerprint"] = command.contract_or_checkpoint_fingerprint
    if command.last_recheck_input_hash is not None:
        context["last_recheck_input_hash"] = command.last_recheck_input_hash
    return cast(RecoveryContextV1, context)


def build_recovery_required_audit_event(
    command: RequireRecoveryCommand, result_code: str, now_ms: int
) -> AuditEventRecord:
    """Canonical RequireRecovery -> RECOVERY_REQUIRED Audit event (11-observability
    -logging-audit.md). Shared by every atomic writer that persists a RequireRecovery
    outcome -- there is exactly one Audit-event shape for this transition.
    """
    return AuditEventRecord(
        account_id=None,
        run_id=command.run_id,
        action_id=command.action_id,
        actor_type="SYSTEM",
        actor_id="run_lifecycle",
        actor_display="Run lifecycle",
        event_type="RECOVERY_REQUIRED",
        outcome=result_code,
        metadata_json=dumps(
            {
                "command_id": command.command_id,
                "reason": command.reason,
                "scope": command.scope,
                "recovery_fingerprint": command.recovery_fingerprint,
            },
            sort_keys=True,
        ),
        created_at_ms=now_ms,
    )
