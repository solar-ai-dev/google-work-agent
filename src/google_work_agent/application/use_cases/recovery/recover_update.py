"""Recover an uncertain UPDATE through a target read, never a resend."""

from __future__ import annotations
from collections.abc import Callable
from json import loads
from typing import cast

from google_work_agent.application.ports import ConnectorExecutionPort
from google_work_agent.application.use_cases.verification.normalize_snapshot import normalize_snapshot
from google_work_agent.application.write_execution_contracts import WriteActionResponse
from google_work_agent.application.write_persistence import require_action, require_approval, require_attempt, resolve_snapshot_fallback_resource_id
from google_work_agent.application.write_recovery_contracts import RecoverExistingWriteResultCommand, RecoverUnknownUpdateActionCommand, ResolveUnknownWriteAsFailedCommand
from google_work_agent.domain import ResultCode
from google_work_agent.ports import UnitOfWork


class RecoverUpdateHandler:
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork], connector_execution: ConnectorExecutionPort, recover_existing_result: Callable[[RecoverExistingWriteResultCommand], WriteActionResponse], resolve_as_failed: Callable[[ResolveUnknownWriteAsFailedCommand], WriteActionResponse]) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._connector_execution = connector_execution
        self._recover_existing_result = recover_existing_result
        self._resolve_as_failed = resolve_as_failed

    def __call__(self, command: RecoverUnknownUpdateActionCommand) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            action = require_action(unit_of_work, command.action_id)
            attempt = require_attempt(unit_of_work, command.attempt_id)
            approval = require_approval(unit_of_work, attempt.approval_id)
            fallback_resource_id = resolve_snapshot_fallback_resource_id(unit_of_work, action=action, resource_ref_id=action.target_resource_ref_id)
        snapshot = self._connector_execution.fetch_verification_snapshot(tool_name=action.tool_name, arguments=loads(action.arguments_json), fallback_resource_id=fallback_resource_id)
        actual = normalize_snapshot(snapshot)
        expected = cast(dict[str, object], loads(action.expected_json))
        if actual == expected:
            return self._recover_existing_result(RecoverExistingWriteResultCommand(command.command_id, command.request_hash, command.action_id, command.attempt_id, command.expected_action_version, command.expected_attempt_version, snapshot))
        source = cast(dict[str, object], loads(approval.source_snapshot_json))
        if actual == source:
            return self._resolve_as_failed(ResolveUnknownWriteAsFailedCommand(command.command_id, command.request_hash, command.action_id, command.attempt_id, command.expected_action_version, command.expected_attempt_version, "NO_RECOVERY_CANDIDATE", "target still matches the approved source snapshot"))
        return WriteActionResponse(False, ResultCode.RECOVERY_REQUIRED.value, action.id, action.status, action.version, (), attempt_id=attempt.id, conflict_detail="UPDATE recovery observed neither expected nor source state; manual resolution required")
