"""Recover an uncertain DELETE through target absence only."""

from __future__ import annotations
from collections.abc import Callable
from json import loads

from google_work_agent.application.ports import ConnectorExecutionPort
from google_work_agent.application.write_action_arguments import dict_argument, required_argument_string
from google_work_agent.application.write_execution_contracts import WriteActionResponse
from google_work_agent.application.write_persistence import require_action, require_attempt
from google_work_agent.application.write_recovery_contracts import RecoverExistingWriteResultCommand, RecoverUnknownDeleteActionCommand
from google_work_agent.domain import PolicyViolationError, ResultCode
from google_work_agent.ports import GoogleWorkspaceErrorCode, GoogleWorkspaceGatewayError, ResourceSnapshot, ResourceType, UnitOfWork

DELETE_TARGETS = {
    "calendar_delete_event": (ResourceType.CALENDAR_EVENT, "event_id", "calendar_id"),
    "tasks_delete_task": (ResourceType.TASK, "task_id", "task_list_id"),
}

class RecoverDeleteHandler:
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork], connector_execution: ConnectorExecutionPort, recover_existing_result: Callable[[RecoverExistingWriteResultCommand], WriteActionResponse]) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._connector_execution = connector_execution
        self._recover_existing_result = recover_existing_result

    def __call__(self, command: RecoverUnknownDeleteActionCommand) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            action = require_action(unit_of_work, command.action_id)
            attempt = require_attempt(unit_of_work, command.attempt_id)
        if action.tool_name not in DELETE_TARGETS:
            raise PolicyViolationError("DELETE recovery requires a registered GET_ABSENT tool")
        arguments = dict_argument(loads(action.arguments_json))
        absent = False
        try:
            self._connector_execution.fetch_verification_snapshot(tool_name=action.tool_name, arguments=arguments, fallback_resource_id=None)
        except LookupError:
            absent = True
        except GoogleWorkspaceGatewayError as error:
            if error.code is not GoogleWorkspaceErrorCode.NOT_FOUND:
                raise
            absent = True
        if not absent:
            return WriteActionResponse(False, ResultCode.RECOVERY_REQUIRED.value, action.id, action.status, action.version, (), attempt_id=attempt.id, conflict_detail="DELETE target is still present; blind re-delete is forbidden")
        resource_type, id_field, parent_field = DELETE_TARGETS[action.tool_name]
        parent_id = required_argument_string(arguments, parent_field)
        snapshot = ResourceSnapshot(fixture_snapshot_id="recovery-absence", resource_type=resource_type, resource_id=required_argument_string(arguments, id_field), parent_id=parent_id, related_resource_ids=(parent_id,), version="deleted", recovery_fingerprint=None, payload={"deleted": True})
        return self._recover_existing_result(RecoverExistingWriteResultCommand(command.command_id, command.request_hash, command.action_id, command.attempt_id, command.expected_action_version, command.expected_attempt_version, snapshot))
