"""Authorize and dispatch exactly one connector write for an executing Attempt."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from json import loads
from typing import cast

from google_work_agent.application.tool_registry.contracts.signed_tool_registry_entry import (
    ToolEffect,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.claim.build_claim_context import (
    ClaimContextV2,
    claim_context_payload,
)
from google_work_agent.application.use_cases.plan.persistence_projection import (
    current_plan_tuple,
    load_plan_record,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.connector.connector_read_port import JsonValue
from google_work_agent.ports.connector.connector_write_port import (
    ConnectorWritePort,
    ConnectorWriteResultV1,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class DispatchConnectorWriteCommandV1:
    action_id: str
    approval_id: str
    execution_attempt_id: str
    tool_id: str
    tool_arguments: dict[str, object]
    claim_context: ClaimContextV2


@dataclass(frozen=True, slots=True)
class DispatchConnectorWriteResultV1:
    connector_result: ConnectorWriteResultV1


class DispatchConnectorWriteHandler:
    """Read-only eligibility gate and sole direct ConnectorWritePort caller."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        tool_registry: SignedToolRegistry,
        connector_write_port: ConnectorWritePort,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._tool_registry = tool_registry
        self._connector_write_port = connector_write_port

    def __call__(self, command: DispatchConnectorWriteCommandV1) -> DispatchConnectorWriteResultV1:
        expected_effect, connector_id = self._verify_dispatch_eligibility(command)
        binding = self._tool_registry.bind_required(
            connector_id,
            command.tool_id,
            expected_effect,
        )
        result = self._connector_write_port.execute_write(
            binding,
            cast(dict[str, JsonValue], command.tool_arguments),
            cast(dict[str, JsonValue], claim_context_payload(command.claim_context)),
        )
        return DispatchConnectorWriteResultV1(connector_result=result)

    def _verify_dispatch_eligibility(
        self, command: DispatchConnectorWriteCommandV1
    ) -> tuple[ToolEffect, str]:
        claim = command.claim_context
        if (
            claim.action_id != command.action_id
            or claim.approval_id != command.approval_id
            or claim.execution_attempt_id != command.execution_attempt_id
        ):
            raise PermissionError("claim persistence identity binding mismatch")
        if claim.tool_name != command.tool_id:
            raise PermissionError("claim tool binding mismatch")
        if calculate_canonical_json_hash(command.tool_arguments) != claim.execution_arguments_hash:
            raise PermissionError("final connector arguments hash mismatch")

        with self._unit_of_work_factory() as unit_of_work:
            attempt = unit_of_work.execution_attempts.get(command.execution_attempt_id)
            action = unit_of_work.actions.get(command.action_id)
            approval = unit_of_work.approvals.get(command.approval_id)
            if attempt is None or action is None or approval is None:
                raise PermissionError("claim persistence binding is missing")
            plan = load_plan_record(unit_of_work.plans, action.plan_id)
            run = None if plan is None else unit_of_work.runs.get(plan.run_id)
            if plan is None or run is None:
                raise PermissionError("claim parent authority is missing")
            current_plans = current_plan_tuple(unit_of_work.plans, run.id)
            current_plan = (
                None
                if not current_plans
                else max(current_plans, key=lambda candidate: candidate.revision_no)
            )
            receipt = unit_of_work.command_receipts.get_by_command_id(
                f"begin-execution-attempt:{command.execution_attempt_id}"
            )

        if (
            attempt.status is not ExecutionAttemptStatusV1.EXECUTING
            or attempt.approval_id != approval.id
            or approval.id != command.approval_id
            or approval.action_id != action.id
            or approval.status is not ApprovalStatusV1.CONSUMED
            or action.status != ActionStatusV1.EXECUTING.value
            or action.tool_name != command.tool_id
            or plan.status is not PlanStatusV1.WAITING_APPROVAL
            or current_plan is None
            or current_plan.id != plan.id
            # CANCEL_REQUESTED is allowed: a RequestCancel applied after this
            # Attempt's BeginExecutionAttempt commit does not retroactively
            # invalidate an already-authorized in-flight dispatch.
            or run.status
            not in {
                RunStatusV1.WAITING_APPROVAL,
                RunStatusV1.VERIFYING,
                RunStatusV1.CANCEL_REQUESTED,
            }
        ):
            raise PermissionError("connector write authority is no longer current")
        if (
            action.arguments_hash != claim.approval_arguments_hash
            or approval.canonical_arguments_hash != claim.approval_arguments_hash
        ):
            raise PermissionError("approved arguments hash mismatch")
        if receipt is None or receipt.status is not CommandReceiptStatus.APPLIED:
            raise PermissionError("successful BeginExecutionAttempt receipt is required")
        try:
            receipt_result = loads(receipt.response_json or "null")
        except (TypeError, ValueError) as error:
            raise PermissionError("BeginExecutionAttempt receipt is malformed") from error
        if not isinstance(receipt_result, Mapping) or (
            receipt_result.get("applied") is not True
            or receipt_result.get("attempt_id") != attempt.id
            or receipt_result.get("attempt_status") != ExecutionAttemptStatusV1.EXECUTING.value
        ):
            raise PermissionError("BeginExecutionAttempt receipt did not authorize dispatch")
        return cast(ToolEffect, action.effect_type), action.connector_id


__all__ = [
    "DispatchConnectorWriteCommandV1",
    "DispatchConnectorWriteHandler",
    "DispatchConnectorWriteResultV1",
]
