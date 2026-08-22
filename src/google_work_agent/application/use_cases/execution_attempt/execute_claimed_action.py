"""Coordinate one claimed connector execution with its canonical durable outcome."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.use_cases.execution_attempt.execute_action import (
    ExecuteActionCommand,
    ExecuteActionResult,
    classify_write_delivery,
)
from google_work_agent.application.use_cases.execution_attempt.mark_failed import (
    MarkFailedCommand,
    MarkFailedResult,
)
from google_work_agent.application.use_cases.execution_attempt.mark_unknown_result import (
    MarkUnknownResultCommand,
    MarkUnknownResultResult,
)
from google_work_agent.application.use_cases.execution_attempt.store_success import (
    StoreSuccessCommand,
    StoreSuccessResult,
)
from google_work_agent.ports import DeliveryCertainty, GoogleWorkspaceGatewayError


@dataclass(frozen=True, slots=True)
class ExecuteClaimedActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    claim_token: str


ExecuteClaimedActionResult = StoreSuccessResult | MarkFailedResult | MarkUnknownResultResult


class ExecuteClaimedActionHandler:
    """Execute once, then route the observed outcome to exactly one finalizer.

    ExecuteAction continues to own only connector dispatch. This coordinator
    owns the application-level operation sequence required by Architecture and
    Sequence contracts: definitive success -> StoreSuccess, definitive
    NOT_SENT -> MarkFailed, and any uncertain delivery -> MarkUnknownResult.
    It never retries a connector write.
    """

    def __init__(
        self,
        *,
        execute_action: Callable[[ExecuteActionCommand], ExecuteActionResult],
        store_success: Callable[[StoreSuccessCommand], StoreSuccessResult],
        mark_failed: Callable[[MarkFailedCommand], MarkFailedResult],
        mark_unknown_result: Callable[[MarkUnknownResultCommand], MarkUnknownResultResult],
    ) -> None:
        self._execute_action = execute_action
        self._store_success = store_success
        self._mark_failed = mark_failed
        self._mark_unknown_result = mark_unknown_result

    def __call__(self, command: ExecuteClaimedActionCommand) -> ExecuteClaimedActionResult:
        try:
            execution = self._execute_action(
                ExecuteActionCommand(
                    action_id=command.action_id,
                    claim_token=command.claim_token,
                    attempt_id=command.attempt_id,
                )
            )
        except GoogleWorkspaceGatewayError as error:
            certainty = classify_write_delivery(error)
            if certainty is DeliveryCertainty.NOT_SENT:
                return self._mark_failed(
                    MarkFailedCommand(
                        command_id=command.command_id,
                        request_hash=command.request_hash,
                        action_id=command.action_id,
                        attempt_id=command.attempt_id,
                        expected_action_version=command.expected_action_version,
                        expected_attempt_version=command.expected_attempt_version,
                        delivery_certainty=certainty,
                        error_code=error.code.value,
                        error_detail=str(error),
                    )
                )
            return self._mark_unknown_result(
                MarkUnknownResultCommand(
                    command_id=command.command_id,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                    attempt_id=command.attempt_id,
                    expected_action_version=command.expected_action_version,
                    expected_attempt_version=command.expected_attempt_version,
                    delivery_certainty=certainty,
                    error_code=error.code.value,
                    error_detail=str(error),
                    mcp_request_id=error.mcp_request_id,
                )
            )

        return self._store_success(
            StoreSuccessCommand(
                command_id=command.command_id,
                request_hash=command.request_hash,
                action_id=command.action_id,
                attempt_id=command.attempt_id,
                expected_action_version=command.expected_action_version,
                expected_attempt_version=command.expected_attempt_version,
                snapshot=execution.snapshot,
            )
        )


__all__ = [
    "ExecuteClaimedActionCommand",
    "ExecuteClaimedActionHandler",
    "ExecuteClaimedActionResult",
]
