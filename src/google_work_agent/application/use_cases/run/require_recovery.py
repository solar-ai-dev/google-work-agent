"""Application use case for require recovery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads
from typing import Literal, cast

from google_work_agent.domain.enums import ResultCode
from google_work_agent.ports.models import AuditEventRecord, CommandReceiptStatus
from google_work_agent.ports.persistence.recovery_repository import (
    RecoveryContextV1,
    RecoveryReasonV1,
)
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
            n = self._n()
            e = u.command_receipts.get_by_command_id(command.command_id)
            if e:
                if e.request_hash != command.request_hash:
                    x = u.runs.get_by_id(command.run_id)
                    return RequireRecoveryResult(
                        False,
                        ResultCode.DUPLICATE_COMMAND.value,
                        x.status.value if x else "UNKNOWN",
                        x.version if x else 0,
                        (),
                        "command_id already exists with a different request_hash",
                    )
                if e.status is CommandReceiptStatus.RECEIVED or e.response_json is None:
                    raise RuntimeError(
                        "RECEIVED receipt requires transaction recovery before replay"
                    )
                p = loads(e.response_json)
                p["next_allowed_commands"] = tuple(p.get("next_allowed_commands", ()))
                return RequireRecoveryResult(**p)

            run = u.runs.get_by_id(command.run_id)
            pre_recovery_status = run.status.value if run else "UNKNOWN"

            u.command_receipts.add_received(
                command_id=command.command_id,
                command_type="RequireRecovery",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=n,
            )
            d = u.runs.require_recovery(command.run_id, expected_version=command.expected_version)
            r = RequireRecoveryResult(
                d.applied,
                d.result_code.value,
                d.current_status.value,
                d.current_version,
                tuple(x.value for x in d.next_allowed_commands),
                d.conflict_detail,
            )
            if r.applied:
                current = u.recovery_contexts.load_current_context(command.run_id)
                next_version = 0 if current is None else current["version"] + 1
                context = _build_context(
                    command,
                    pre_recovery_status=pre_recovery_status,
                    version=next_version,
                    now_ms=n,
                )
                u.recovery_contexts.store_context(context)
                u.audits.add(_audit(command, r, n))
            u.command_receipts.finish_json(
                command_id=command.command_id,
                applied=r.applied,
                result_code=d.result_code,
                result_version=r.current_version,
                response_json=dumps(asdict(r), sort_keys=True),
                completed_at_ms=n,
            )
            u.commit()
            return r


def _build_context(
    command: RequireRecoveryCommand,
    *,
    pre_recovery_status: str,
    version: int,
    now_ms: int,
) -> RecoveryContextV1:
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
        context["observed_external_state_fingerprint"] = (
            command.observed_external_state_fingerprint
        )
    if command.verification_input_fingerprint is not None:
        context["verification_input_fingerprint"] = command.verification_input_fingerprint
    if command.contract_or_checkpoint_fingerprint is not None:
        context["contract_or_checkpoint_fingerprint"] = (
            command.contract_or_checkpoint_fingerprint
        )
    if command.last_recheck_input_hash is not None:
        context["last_recheck_input_hash"] = command.last_recheck_input_hash
    return cast(RecoveryContextV1, context)


def _audit(
    command: RequireRecoveryCommand, result: RequireRecoveryResult, now_ms: int
) -> AuditEventRecord:
    return AuditEventRecord(
        account_id=None,
        run_id=command.run_id,
        action_id=command.action_id,
        actor_type="SYSTEM",
        actor_id="run_lifecycle",
        actor_display="Run lifecycle",
        event_type="RECOVERY_REQUIRED",
        outcome=result.result_code,
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
