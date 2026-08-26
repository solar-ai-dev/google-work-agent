"""Application use case for explicit Run recovery resolution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads

from google_work_agent.domain.enums import (
    ActionStatus,
    RecoveryResolution,
    ResultCode,
    RunStatus,
)
from google_work_agent.domain.recovery.transitions.resolve_recovery import (
    transition_resolve_recovery,
)
from google_work_agent.ports.models import CommandReceiptStatus
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ResolveRecoveryCommand:
    run_id: str
    expected_version: int
    command_id: str
    request_hash: str
    resolution: RecoveryResolution
    cancel_intent_active: bool = False
    terminal_snapshot: bool = False
    irrecoverable_confirmed: bool = False
    recheck_input_changed: bool = False
    recovered_action_status: ActionStatus | None = None
    validated_resume_status: RunStatus | None = None
    unresolved_external_effect_count: int = 0


@dataclass(frozen=True, slots=True)
class ResolveRecoveryResult:
    applied: bool
    result_code: str
    current_status: str
    current_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None


class ResolveRecoveryHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: ResolveRecoveryCommand) -> ResolveRecoveryResult:
        with self._unit_of_work_factory() as unit_of_work:
            now_ms = self._now_ms()
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._replay_or_reject_duplicate(unit_of_work, command, existing)

            run = unit_of_work.runs.get_by_id(command.run_id)
            if run is None:
                raise LookupError(f"run not found: {command.run_id}")
            context = unit_of_work.recovery_contexts.load_current_context(command.run_id)
            if context is None:
                raise RuntimeError("ResolveRecovery requires a durable RecoveryContextV1")

            decision = transition_resolve_recovery(
                run.status,
                resolution=command.resolution,
                reason=context["reason"],
                pre_recovery_status=RunStatus(context["pre_recovery_status"]),
                recheck_input_changed=command.recheck_input_changed,
                recovered_action_status=self._recovered_action_status(
                    unit_of_work, command, context
                ),
                validated_resume_status=command.validated_resume_status,
                cancel_intent_active=command.cancel_intent_active,
                unresolved_external_effect_count=command.unresolved_external_effect_count,
                irrecoverable_confirmed=command.irrecoverable_confirmed,
            )
            if not decision.applied:
                result = ResolveRecoveryResult(
                    applied=False,
                    result_code=decision.result_code.value,
                    current_status=run.status.value,
                    current_version=run.version,
                    next_allowed_commands=(),
                    conflict_detail=decision.conflict_detail,
                )
                self._store_result(unit_of_work, command, result, now_ms)
                unit_of_work.commit()
                return result

            target = decision.current_status
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="ResolveRecovery",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            persisted = unit_of_work.runs.resolve_recovery(
                command.run_id,
                expected_version=command.expected_version,
                recovery_next_status=target,
                finished_at_ms=(
                    now_ms
                    if target in {RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED}
                    else None
                ),
                validated_recovery_target=True,
            )
            result = ResolveRecoveryResult(
                applied=persisted.applied,
                result_code=persisted.result_code.value,
                current_status=persisted.current_status.value,
                current_version=persisted.current_version,
                next_allowed_commands=tuple(item.value for item in persisted.next_allowed_commands),
                conflict_detail=persisted.conflict_detail,
            )
            unit_of_work.command_receipts.finish_json(
                command_id=command.command_id,
                applied=result.applied,
                result_code=persisted.result_code,
                result_version=result.current_version,
                response_json=dumps(asdict(result), sort_keys=True),
                completed_at_ms=now_ms,
            )
            unit_of_work.commit()
            return result

    @staticmethod
    def _recovered_action_status(
        unit_of_work: UnitOfWork,
        command: ResolveRecoveryCommand,
        context: dict[str, object],
    ) -> ActionStatus | None:
        if command.recovered_action_status is not None:
            return command.recovered_action_status
        action_id = context.get("action_id")
        if action_id is None:
            return None
        action = unit_of_work.actions.get_by_id(str(action_id))
        return None if action is None else ActionStatus(action.status)

    @staticmethod
    def _replay_or_reject_duplicate(
        unit_of_work: UnitOfWork,
        command: ResolveRecoveryCommand,
        receipt: object,
    ) -> ResolveRecoveryResult:
        if receipt.request_hash != command.request_hash:
            run = unit_of_work.runs.get_by_id(command.run_id)
            return ResolveRecoveryResult(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                current_status=run.status.value if run else "UNKNOWN",
                current_version=run.version if run else 0,
                next_allowed_commands=(),
                conflict_detail="command_id already exists with a different request_hash",
            )
        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            raise RuntimeError("RECEIVED receipt requires transaction recovery before replay")
        payload = loads(receipt.response_json)
        payload["next_allowed_commands"] = tuple(payload.get("next_allowed_commands", ()))
        return ResolveRecoveryResult(**payload)

    @staticmethod
    def _store_result(
        unit_of_work: UnitOfWork,
        command: ResolveRecoveryCommand,
        result: ResolveRecoveryResult,
        now_ms: int,
    ) -> None:
        unit_of_work.command_receipts.add_received(
            command_id=command.command_id,
            command_type="ResolveRecovery",
            request_hash=command.request_hash,
            aggregate_type="Run",
            aggregate_id=command.run_id,
            created_at_ms=now_ms,
        )
        unit_of_work.command_receipts.finish_json(
            command_id=command.command_id,
            applied=False,
            result_code=ResultCode(result.result_code),
            result_version=result.current_version,
            response_json=dumps(asdict(result), sort_keys=True),
            completed_at_ms=now_ms,
        )
