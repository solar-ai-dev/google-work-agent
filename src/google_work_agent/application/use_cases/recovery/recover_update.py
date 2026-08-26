"""Recover an uncertain UPDATE through a target read, never a resend."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from json import loads
from typing import cast

from google_work_agent.application.recovery_source_projection import (
    project_source_resource,
)
from google_work_agent.application.use_cases.recovery.recover_existing_result import (
    RecoverExistingResultCommand,
    RecoverExistingResultResult,
)
from google_work_agent.application.use_cases.recovery.resolve_as_failed import (
    ResolveAsFailedCommand,
    ResolveAsFailedResult,
)
from google_work_agent.application.use_cases.verification.normalize_snapshot import (
    normalize_snapshot,
)
from google_work_agent.application.write_persistence import (
    require_action,
    require_approval,
    require_attempt,
    resolve_snapshot_fallback_resource_id,
)
from google_work_agent.application.write_verification_projection import (
    calculate_verification_subset_diff,
    normalize_actual_verification_projection,
)
from google_work_agent.domain.results import ResultCode
from google_work_agent.ports import UnitOfWork
from google_work_agent.ports.connector.connector_write_port import (
    ConnectorWritePort,
)


@dataclass(frozen=True, slots=True)
class RecoverUpdateCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int


@dataclass(frozen=True, slots=True)
class RecoverUpdateResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    attempt_id: str | None = None
    safe_error_code: str | None = None
    conflict_detail: str | None = None


def _to_result(
    response: RecoverExistingResultResult | ResolveAsFailedResult,
) -> RecoverUpdateResult:
    return RecoverUpdateResult(
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


class RecoverUpdateHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        connector_execution: ConnectorWritePort,
        recover_existing_result: Callable[
            [RecoverExistingResultCommand], RecoverExistingResultResult
        ],
        resolve_as_failed: Callable[[ResolveAsFailedCommand], ResolveAsFailedResult],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._connector_execution = connector_execution
        self._recover_existing_result = recover_existing_result
        self._resolve_as_failed = resolve_as_failed

    def __call__(self, command: RecoverUpdateCommand) -> RecoverUpdateResult:
        with self._unit_of_work_factory() as unit_of_work:
            action = require_action(unit_of_work, command.action_id)
            attempt = require_attempt(unit_of_work, command.attempt_id)
            approval = require_approval(unit_of_work, attempt.approval_id)
            fallback_resource_id = resolve_snapshot_fallback_resource_id(
                unit_of_work,
                action=action,
                resource_ref_id=action.target_resource_ref_id,
            )

        snapshot = self._connector_execution.fetch_verification_snapshot(
            tool_name=action.tool_name,
            arguments=loads(action.arguments_json),
            fallback_resource_id=fallback_resource_id,
        )
        actual_projection = normalize_actual_verification_projection(
            tool_name=action.tool_name,
            actual=normalize_snapshot(snapshot),
        )
        expected = cast(dict[str, object], loads(action.expected_json))

        if not calculate_verification_subset_diff(expected, actual_projection):
            return _to_result(
                self._recover_existing_result(
                    RecoverExistingResultCommand(
                        command.command_id,
                        command.request_hash,
                        command.action_id,
                        command.attempt_id,
                        command.expected_action_version,
                        command.expected_attempt_version,
                        snapshot,
                    )
                )
            )

        source = cast(dict[str, object], loads(approval.source_snapshot_json))
        source_resource = project_source_resource(source)
        if source_resource is not None:
            source_projection = normalize_actual_verification_projection(
                tool_name=action.tool_name,
                actual=source_resource,
            )
            if not calculate_verification_subset_diff(source_projection, actual_projection):
                return _to_result(
                    self._resolve_as_failed(
                        ResolveAsFailedCommand(
                            command.command_id,
                            command.request_hash,
                            command.action_id,
                            command.attempt_id,
                            command.expected_action_version,
                            command.expected_attempt_version,
                            "NO_RECOVERY_CANDIDATE",
                            "target still matches the approved source snapshot",
                        )
                    )
                )

        return RecoverUpdateResult(
            False,
            ResultCode.RECOVERY_REQUIRED.value,
            action.id,
            action.status,
            action.version,
            (),
            attempt_id=attempt.id,
            conflict_detail=(
                "UPDATE recovery observed neither expected nor authoritative source state; "
                "manual resolution required"
            ),
        )
