"""Settle a claimed execution attempt before any provider dispatch."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from json import dumps
from typing import cast

from google_work_agent.application.cancel_intent import (
    CancelIntentReceiptReader,
    has_durable_cancel_intent,
)
from google_work_agent.application.write_persistence import (
    require_action,
    require_attempt,
    require_plan,
    require_run,
)
from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.execution_attempt.transitions.abort_claimed_execution import (
    AbortClaimedExecutionDecision,
    transition_abort_claimed_execution,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

AbortClaimedExecutionResult = AbortClaimedExecutionDecision


@dataclass(frozen=True, slots=True)
class AbortClaimedExecutionCommand:
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    error_code: str
    error_detail: str


class AbortClaimedExecutionHandler:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: AbortClaimedExecutionCommand) -> AbortClaimedExecutionDecision:
        with self._unit_of_work_factory() as unit_of_work:
            decision = self.apply_in_unit_of_work(unit_of_work, command, now_ms=self._now_ms())
            unit_of_work.commit()
            return decision

    @staticmethod
    def apply_in_unit_of_work(
        unit_of_work: UnitOfWork,
        command: AbortClaimedExecutionCommand,
        *,
        now_ms: int,
    ) -> AbortClaimedExecutionDecision:
        action = require_action(unit_of_work, command.action_id)
        attempt = require_attempt(unit_of_work, command.attempt_id)
        plan = require_plan(unit_of_work, action.plan_id)
        run = require_run(unit_of_work, plan.run_id)
        begin_receipt = unit_of_work.command_receipts.get_by_command_id(
            f"begin-execution-attempt:{attempt.id}"
        )
        decision = transition_abort_claimed_execution(
            action_status=ActionStatus(action.status),
            action_version=action.version,
            expected_action_version=command.expected_action_version,
            attempt_status=attempt.status,
            attempt_version=attempt.version,
            expected_attempt_version=command.expected_attempt_version,
            durable_cancel_intent=has_durable_cancel_intent(
                cast(CancelIntentReceiptReader, unit_of_work.command_receipts), run.id
            ),
            begin_receipt_applied=(
                begin_receipt is not None and begin_receipt.status is CommandReceiptStatus.APPLIED
            ),
            provider_dispatch_count=0,
        )
        if not decision.applied:
            return decision

        updated_attempt = unit_of_work.execution_attempts.update_if_version_and_status(
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
            unit_of_work.actions.update_if_version_and_status(
                action.id,
                expected_version=action.version,
                expected_status=ActionStatus(action.status),
                next_status=decision.action_status,
                updated_at_ms=now_ms,
            )
            is None
        ):
            raise RuntimeError("validated AbortClaimedExecution Action CAS failed")
        return decision


__all__ = [
    "AbortClaimedExecutionCommand",
    "AbortClaimedExecutionHandler",
    "AbortClaimedExecutionResult",
]
