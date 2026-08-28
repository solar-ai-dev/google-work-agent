"""Test-only historical CREATE recovery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.use_cases.execution_attempt.recover_existing_result import (
    RecoverExistingResultCommand,
    RecoverExistingResultResult,
)
from google_work_agent.application.write_dispatch_models import WriteResultMaterializer
from google_work_agent.application.write_persistence import (
    require_action,
    require_approval,
    require_attempt,
)
from google_work_agent.domain.results import ResultCode
from google_work_agent.ports import UnitOfWork


@dataclass(frozen=True, slots=True)
class RecoverCreateCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int


@dataclass(frozen=True, slots=True)
class RecoverCreateResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    attempt_id: str | None = None
    safe_error_code: str | None = None
    conflict_detail: str | None = None


def _to_result(response: RecoverExistingResultResult) -> RecoverCreateResult:
    return RecoverCreateResult(
        applied=response.applied,
        result_code=response.result_code,
        action_id=response.action_id,
        action_status=response.action_status,
        action_version=response.action_version,
        next_allowed_commands=response.next_allowed_commands,
        attempt_id=response.attempt_id,
        safe_error_code=response.safe_error_code,
        conflict_detail=response.conflict_detail,
    )


class RecoverCreateHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        connector_execution: WriteResultMaterializer,
        recover_existing_result: Callable[
            [RecoverExistingResultCommand], RecoverExistingResultResult
        ],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._connector_execution = connector_execution
        self._recover_existing_result = recover_existing_result

    def __call__(self, command: RecoverCreateCommand) -> RecoverCreateResult:
        with self._unit_of_work_factory() as unit_of_work:
            action = require_action(unit_of_work, command.action_id)
            attempt = require_attempt(unit_of_work, command.attempt_id)
            approval = require_approval(unit_of_work, attempt.approval_id)

        candidates = self._connector_execution.search_recovery_candidates(
            tool_name=action.tool_name,
            recovery_fingerprint=approval.recovery_fingerprint,
        )
        if len(candidates) != 1:
            return RecoverCreateResult(
                False,
                ResultCode.RECOVERY_REQUIRED.value,
                action.id,
                action.status,
                action.version,
                (),
                attempt_id=attempt.id,
                conflict_detail=(
                    "CREATE recovery requires exactly one existing candidate; "
                    "blind recreate is forbidden"
                ),
            )

        return _to_result(
            self._recover_existing_result(
                RecoverExistingResultCommand(
                    command.command_id,
                    command.request_hash,
                    command.action_id,
                    command.attempt_id,
                    command.expected_action_version,
                    command.expected_attempt_version,
                    candidates[0],
                )
            )
        )
