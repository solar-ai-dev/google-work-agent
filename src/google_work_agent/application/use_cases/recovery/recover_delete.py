"""Recover an uncertain DELETE through target absence only."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from json import loads

from google_work_agent.application.ports import ConnectorExecutionPort
from google_work_agent.application.use_cases.recovery.recover_existing_result import (
    RecoverExistingResultCommand,
    RecoverExistingResultResult,
)
from google_work_agent.application.write_action_arguments import dict_argument, required_argument_string
from google_work_agent.application.write_persistence import require_action, require_attempt
from google_work_agent.domain import PolicyViolationError, ResultCode
from google_work_agent.ports import (
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourceSnapshot,
    ResourceType,
    UnitOfWork,
)

DELETE_TARGETS = {
    "calendar_delete_event": (ResourceType.CALENDAR_EVENT, "event_id", "calendar_id"),
    "tasks_delete_task": (ResourceType.TASK, "task_id", "task_list_id"),
}


@dataclass(frozen=True, slots=True)
class RecoverDeleteCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int


@dataclass(frozen=True, slots=True)
class RecoverDeleteResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    attempt_id: str | None = None
    safe_error_code: str | None = None
    conflict_detail: str | None = None


def _to_result(response: RecoverExistingResultResult) -> RecoverDeleteResult:
    return RecoverDeleteResult(
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


class RecoverDeleteHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        connector_execution: ConnectorExecutionPort,
        recover_existing_result: Callable[
            [RecoverExistingResultCommand], RecoverExistingResultResult
        ],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._connector_execution = connector_execution
        self._recover_existing_result = recover_existing_result

    def __call__(self, command: RecoverDeleteCommand) -> RecoverDeleteResult:
        with self._unit_of_work_factory() as unit_of_work:
            action = require_action(unit_of_work, command.action_id)
            attempt = require_attempt(unit_of_work, command.attempt_id)

        if action.tool_name not in DELETE_TARGETS:
            raise PolicyViolationError("DELETE recovery requires a registered GET_ABSENT tool")

        arguments = dict_argument(loads(action.arguments_json))
        absent = False
        try:
            self._connector_execution.fetch_verification_snapshot(
                tool_name=action.tool_name,
                arguments=arguments,
                fallback_resource_id=None,
            )
        except LookupError:
            absent = True
        except GoogleWorkspaceGatewayError as error:
            if error.code is not GoogleWorkspaceErrorCode.NOT_FOUND:
                raise
            absent = True

        if not absent:
            return RecoverDeleteResult(
                False,
                ResultCode.RECOVERY_REQUIRED.value,
                action.id,
                action.status,
                action.version,
                (),
                attempt_id=attempt.id,
                conflict_detail="DELETE target is still present; blind re-delete is forbidden",
            )

        resource_type, id_field, parent_field = DELETE_TARGETS[action.tool_name]
        parent_id = required_argument_string(arguments, parent_field)
        snapshot = ResourceSnapshot(
            fixture_snapshot_id="recovery-absence",
            resource_type=resource_type,
            resource_id=required_argument_string(arguments, id_field),
            parent_id=parent_id,
            related_resource_ids=(parent_id,),
            version="deleted",
            recovery_fingerprint=None,
            payload={"deleted": True},
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
                    snapshot,
                )
            )
        )
