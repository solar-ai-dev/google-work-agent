"""Recover an uncertain CREATE without dispatching a new write."""

from __future__ import annotations
from collections.abc import Callable

from google_work_agent.application.ports import ConnectorExecutionPort
from google_work_agent.application.write_execution_contracts import WriteActionResponse
from google_work_agent.application.write_persistence import require_action, require_approval, require_attempt
from google_work_agent.application.write_recovery_contracts import RecoverExistingWriteResultCommand, RecoverUnknownCreateActionCommand
from google_work_agent.domain import ResultCode
from google_work_agent.ports import UnitOfWork


class RecoverCreateHandler:
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork], connector_execution: ConnectorExecutionPort, recover_existing_result: Callable[[RecoverExistingWriteResultCommand], WriteActionResponse]) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._connector_execution = connector_execution
        self._recover_existing_result = recover_existing_result

    def __call__(self, command: RecoverUnknownCreateActionCommand) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            action = require_action(unit_of_work, command.action_id)
            attempt = require_attempt(unit_of_work, command.attempt_id)
            approval = require_approval(unit_of_work, attempt.approval_id)
        candidates = self._connector_execution.search_recovery_candidates(tool_name=action.tool_name, recovery_fingerprint=approval.recovery_fingerprint)
        if len(candidates) != 1:
            return WriteActionResponse(False, ResultCode.RECOVERY_REQUIRED.value, action.id, action.status, action.version, (), attempt_id=attempt.id, conflict_detail="CREATE recovery requires exactly one existing candidate; blind recreate is forbidden")
        return self._recover_existing_result(RecoverExistingWriteResultCommand(command.command_id, command.request_hash, command.action_id, command.attempt_id, command.expected_action_version, command.expected_attempt_version, candidates[0]))
