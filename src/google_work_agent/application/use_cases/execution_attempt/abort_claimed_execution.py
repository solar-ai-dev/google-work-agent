"""Settle a claimed Attempt before provider dispatch, with Receipt and Audit."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads

from google_work_agent.application.use_cases.action.persistence_cas import (
    update_action_record,
    update_execution_attempt_record,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    audit_event,
    require_action,
    require_attempt,
    require_plan,
    require_run,
)
from google_work_agent.application.use_cases.run.cancel_intent import has_durable_cancel_intent
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.command_receipt.model import (
    CommandReceipt as CommandReceiptRecord,
)
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.execution_attempt.transitions.abort_claimed_execution import (
    AbortClaimedExecutionDecision,
    transition_abort_claimed_execution,
)
from google_work_agent.domain.results import ResultCode
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class AbortClaimedExecutionCommandV1:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    error_code: str
    error_detail: str


@dataclass(frozen=True, slots=True)
class AbortClaimedExecutionResultV1:
    applied: bool
    result_code: ResultCode
    action_status: ActionStatusV1
    action_version: int
    attempt_status: ExecutionAttemptStatusV1
    attempt_version: int
    conflict_detail: str | None = None
    request_replayed: bool = False

    @classmethod
    def from_decision(
        cls, decision: AbortClaimedExecutionDecision
    ) -> AbortClaimedExecutionResultV1:
        return cls(
            decision.applied,
            decision.result_code,
            decision.action_status,
            decision.action_version,
            decision.attempt_status,
            decision.attempt_version,
            decision.conflict_detail,
        )


class AbortClaimedExecutionHandler:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: AbortClaimedExecutionCommandV1) -> AbortClaimedExecutionResultV1:
        with self._unit_of_work_factory() as unit_of_work:
            result = self.apply_in_unit_of_work(unit_of_work, command, now_ms=self._now_ms())
            unit_of_work.commit()
            return result

    @staticmethod
    def apply_in_unit_of_work(
        unit_of_work: UnitOfWork,
        command: AbortClaimedExecutionCommandV1,
        *,
        now_ms: int,
    ) -> AbortClaimedExecutionResultV1:
        expected_hash = calculate_canonical_json_hash(
            {
                "action_id": command.action_id,
                "attempt_id": command.attempt_id,
                "expected_action_version": command.expected_action_version,
                "expected_attempt_version": command.expected_attempt_version,
                "error_code": command.error_code,
                "error_detail": command.error_detail,
            }
        )
        if command.request_hash != expected_hash:
            raise PermissionError("AbortClaimedExecution request_hash mismatch")
        existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
        if existing is not None:
            return AbortClaimedExecutionHandler._replay(unit_of_work, command, existing)
        unit_of_work.command_receipts.reserve_or_replay(
            command_id=command.command_id,
            command_type="AbortClaimedExecution",
            request_hash=command.request_hash,
            aggregate_type="ExecutionAttempt",
            aggregate_id=command.attempt_id,
            created_at_ms=now_ms,
        )
        action = require_action(unit_of_work, command.action_id)
        attempt = require_attempt(unit_of_work, command.attempt_id)
        plan = require_plan(unit_of_work, action.plan_id)
        run = require_run(unit_of_work, plan.run_id)
        begin_receipt = unit_of_work.command_receipts.get_by_command_id(
            f"begin-execution-attempt:{attempt.id}"
        )
        decision = transition_abort_claimed_execution(
            action_status=ActionStatusV1(action.status),
            action_version=action.version,
            expected_action_version=command.expected_action_version,
            attempt_status=attempt.status,
            attempt_version=attempt.version,
            expected_attempt_version=command.expected_attempt_version,
            durable_cancel_intent=has_durable_cancel_intent(unit_of_work.command_receipts, run.id),
            begin_receipt_applied=(
                begin_receipt is not None and begin_receipt.status is CommandReceiptStatus.APPLIED
            ),
            provider_dispatch_count=0,
        )
        if decision.applied:
            updated_attempt = update_execution_attempt_record(
                unit_of_work,
                attempt.id,
                expected_version=attempt.version,
                expected_status=attempt.status,
                status=decision.attempt_status,
                error_code=command.error_code,
                error_detail_json=dumps({"detail": command.error_detail}, sort_keys=True),
                result_resource_ref_id=None,
                response_metadata_json=None,
                finished_at_ms=now_ms,
            )
            if updated_attempt is None:
                raise RuntimeError("validated AbortClaimedExecution Attempt CAS failed")
            if (
                update_action_record(
                    unit_of_work,
                    action.id,
                    expected_version=action.version,
                    expected_status=ActionStatusV1(action.status),
                    next_status=decision.action_status,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError("validated AbortClaimedExecution Action CAS failed")
            unit_of_work.audits.append(
                audit_event(
                    run_id=run.id,
                    action_id=action.id,
                    event_type="EXECUTION_CLAIM_ABORTED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={
                        "attempt_id": attempt.id,
                        "command_id": command.command_id,
                        "provider_dispatch_count": 0,
                    },
                    created_at_ms=now_ms,
                )
            )
        result = AbortClaimedExecutionResultV1.from_decision(decision)
        AbortClaimedExecutionHandler._finish(unit_of_work, command.command_id, result, now_ms)
        return result

    @staticmethod
    def _finish(
        unit_of_work: UnitOfWork,
        command_id: str,
        result: AbortClaimedExecutionResultV1,
        now_ms: int,
    ) -> None:
        payload = asdict(result)
        payload["result_code"] = result.result_code.value
        payload["action_status"] = result.action_status.value
        payload["attempt_status"] = result.attempt_status.value
        unit_of_work.command_receipts.store_result(
            command_id=command_id,
            applied=result.applied,
            result_code=result.result_code,
            result_version=max(result.action_version, result.attempt_version),
            response_json=dumps(payload, sort_keys=True),
            completed_at_ms=now_ms,
        )

    @staticmethod
    def _replay(
        unit_of_work: UnitOfWork,
        command: AbortClaimedExecutionCommandV1,
        receipt: CommandReceiptRecord,
    ) -> AbortClaimedExecutionResultV1:
        action = require_action(unit_of_work, command.action_id)
        attempt = require_attempt(unit_of_work, command.attempt_id)
        if receipt.request_hash != command.request_hash:
            return AbortClaimedExecutionResultV1(
                False,
                ResultCode.DUPLICATE_COMMAND,
                ActionStatusV1(action.status),
                action.version,
                attempt.status,
                attempt.version,
                "command_id already exists with a different request_hash",
                True,
            )
        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            raise RuntimeError("RECEIVED AbortClaimedExecution receipt requires recovery")
        payload = loads(receipt.response_json)
        return AbortClaimedExecutionResultV1(
            bool(payload["applied"]),
            ResultCode(payload["result_code"]),
            ActionStatusV1(payload["action_status"]),
            int(payload["action_version"]),
            ExecutionAttemptStatusV1(payload["attempt_status"]),
            int(payload["attempt_version"]),
            payload.get("conflict_detail"),
            True,
        )


__all__ = [
    "AbortClaimedExecutionCommandV1",
    "AbortClaimedExecutionHandler",
    "AbortClaimedExecutionResultV1",
]
