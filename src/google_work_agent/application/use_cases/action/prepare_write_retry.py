"""Canonical persisted application use case for FAILED write retry preparation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from json import dumps, loads

from google_work_agent.application.use_cases.action.persistence_cas import update_action_record
from google_work_agent.application.use_cases.action.write_persistence import (
    audit_event,
    emit_command_rejected_hash_mismatch,
    require_plan_review,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionCommand, ActionStatusV1, EffectType
from google_work_agent.domain.action.transitions.prepare_write_retry import (
    transition_prepare_write_retry,
)
from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class PrepareWriteRetryCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_action_version: int


@dataclass(frozen=True, slots=True)
class PrepareWriteRetryResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    approval_id: str | None = None
    attempt_id: str | None = None
    claim_token: str | None = None
    safe_error_code: str | None = None
    request_replayed: bool = False
    conflict_detail: str | None = None


class PrepareWriteRetryHandler:
    """Move only a durable FAILED write back to MODIFIED for fresh review/approval."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: PrepareWriteRetryCommand) -> PrepareWriteRetryResult:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._resolve_existing_receipt(unit_of_work, existing, command)

            now_ms = self._now_ms()
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="PrepareWriteRetry",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = self._require_action(unit_of_work, command.action_id)
            plan = unit_of_work.plans.load_bundle(action.plan_id)
            if plan is None:
                raise LookupError(f"plan not found: {action.plan_id}")
            current_plan = max(
                current_plan_tuple(unit_of_work.plans, plan.run_id),
                key=lambda candidate: getattr(candidate, "revision_no", 0),
                default=None,
            )
            if plan.status is PlanStatusV1.SUPERSEDED:
                return self._finish(
                    unit_of_work,
                    command,
                    self._result(
                        action=action,
                        result_code=ResultCode.STATE_CONFLICT,
                        conflict_detail="superseded Plan children are history-only",
                    ),
                    now_ms,
                )

            preview = transition_prepare_write_retry(
                ActionStatusV1(action.status),
                action.version,
                command.expected_action_version,
                effect_type=EffectType(action.effect_type),
                plan_status=plan.status,
                plan_is_current=current_plan is not None and current_plan.id == plan.id,
            )
            if not preview.applied:
                response = PrepareWriteRetryResult(
                    applied=False,
                    result_code=preview.result_code.value,
                    action_id=action.id,
                    action_status=preview.current_status.value,
                    action_version=preview.current_version,
                    next_allowed_commands=tuple(
                        item.value for item in preview.next_allowed_commands
                    ),
                    conflict_detail=preview.conflict_detail,
                )
                return self._finish(unit_of_work, command, response, now_ms)

            if (
                update_action_record(
                    unit_of_work,
                    action.id,
                    expected_version=action.version,
                    expected_status=ActionStatusV1(action.status),
                    next_status=preview.current_status,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError("validated PrepareWriteRetry CAS failed")
            result = preview
            if not result.applied:
                response = PrepareWriteRetryResult(
                    applied=False,
                    result_code=result.result_code.value,
                    action_id=action.id,
                    action_status=result.current_status.value,
                    action_version=result.current_version,
                    next_allowed_commands=tuple(
                        item.value for item in result.next_allowed_commands
                    ),
                    conflict_detail=result.conflict_detail,
                )
                return self._finish(unit_of_work, command, response, now_ms)

            review_version = require_plan_review(unit_of_work, action.plan_id)
            response = PrepareWriteRetryResult(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                action_id=action.id,
                action_status=result.current_status.value,
                action_version=result.current_version,
                next_allowed_commands=tuple(
                    item.value
                    for item in result.next_allowed_commands
                    if item is not ActionCommand.APPROVE_ACTION
                ),
            )
            unit_of_work.traces.append(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_RETRY_PREPARED",
                    status=ActionStatusV1.MODIFIED.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {
                            "action_id": action.id,
                            "command_id": command.command_id,
                            "review_version": review_version,
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.append(
                audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_RETRY_PREPARED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={
                        "action_id": action.id,
                        "command_id": command.command_id,
                        "previous_status": action.status,
                        "new_status": result.current_status.value,
                        "plan_id": plan.id,
                        "review_version": review_version,
                    },
                    created_at_ms=now_ms,
                )
            )
            return self._finish(unit_of_work, command, response, now_ms)

    def _resolve_existing_receipt(
        self,
        unit_of_work: UnitOfWork,
        receipt: CommandReceiptRecord,
        command: PrepareWriteRetryCommand,
    ) -> PrepareWriteRetryResult:
        if receipt.request_hash != command.request_hash:
            emit_command_rejected_hash_mismatch(
                unit_of_work=unit_of_work,
                receipt=receipt,
                run_id=None,
                action_id=command.action_id,
                now_ms=self._now_ms(),
            )
            action = unit_of_work.actions.get(command.action_id)
            if action is None:
                return PrepareWriteRetryResult(
                    applied=False,
                    result_code=ResultCode.DUPLICATE_COMMAND.value,
                    action_id=command.action_id,
                    action_status="UNKNOWN",
                    action_version=receipt.result_version or 0,
                    next_allowed_commands=(),
                    request_replayed=True,
                    conflict_detail="command_id already exists with a different request_hash",
                )
            return replace(
                self._result(
                    action=action,
                    result_code=ResultCode.DUPLICATE_COMMAND,
                    conflict_detail="command_id already exists with a different request_hash",
                ),
                request_replayed=True,
            )

        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            raise RuntimeError("RECEIVED receipt recovery requires aggregate-specific handling")
        payload = loads(receipt.response_json)
        if not isinstance(payload, dict):
            raise RuntimeError("prepare retry receipt response must be an object")
        payload.setdefault("approval_id", None)
        payload.setdefault("attempt_id", None)
        payload.setdefault("claim_token", None)
        payload.setdefault("safe_error_code", None)
        payload.setdefault("request_replayed", False)
        payload["next_allowed_commands"] = tuple(payload["next_allowed_commands"])
        return replace(PrepareWriteRetryResult(**payload), request_replayed=True)

    @staticmethod
    def _finish(
        unit_of_work: UnitOfWork,
        command: PrepareWriteRetryCommand,
        response: PrepareWriteRetryResult,
        now_ms: int,
    ) -> PrepareWriteRetryResult:
        unit_of_work.command_receipts.store_result(
            command_id=command.command_id,
            applied=response.applied,
            result_code=ResultCode(response.result_code),
            result_version=response.action_version,
            response_json=dumps(asdict(response), sort_keys=True),
            completed_at_ms=now_ms,
        )
        unit_of_work.commit()
        return response

    @staticmethod
    def _result(
        *,
        action: ActionRecord,
        result_code: ResultCode,
        conflict_detail: str | None,
    ) -> PrepareWriteRetryResult:
        from google_work_agent.domain.action.model import next_allowed_action_commands

        return PrepareWriteRetryResult(
            applied=False,
            result_code=result_code.value,
            action_id=action.id,
            action_status=action.status,
            action_version=action.version,
            next_allowed_commands=tuple(
                item.value
                for item in next_allowed_action_commands(
                    ActionStatusV1(action.status), effect_type=EffectType(action.effect_type)
                )
            ),
            conflict_detail=conflict_detail,
        )

    @staticmethod
    def _require_action(unit_of_work: UnitOfWork, action_id: str) -> ActionRecord:
        action = unit_of_work.actions.get(action_id)
        if action is None:
            raise LookupError(f"action not found: {action_id}")
        return action
