"""Canonical persisted ExpireApproval application boundary."""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.action.persistence_cas import (
    update_action_record,
    update_approval_status,
)
from google_work_agent.application.use_cases.plan.persistence_projection import (
    current_plan_tuple,
    load_plan_record,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.guards.expire_approval import ApprovalExpiryInput
from google_work_agent.domain.approval.transitions.expire_approval import (
    transition_expire_approval,
)
from google_work_agent.domain.audit_event.model import AuditEvent
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ExpireApprovalCommand:
    command_id: str
    request_hash: str
    approval_id: str
    expected_action_version: int
    current_source_snapshot: dict[str, object]


@dataclass(frozen=True, slots=True)
class ExpireApprovalResult:
    applied: bool
    result_code: str
    approval_id: str
    approval_status: str
    action_id: str
    action_status: str
    action_version: int
    conflict_detail: str | None = None


class ExpireApprovalHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        tool_registry: SignedToolRegistry,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._registry = tool_registry

    def __call__(self, command: ExpireApprovalCommand) -> ExpireApprovalResult:
        with self._unit_of_work_factory() as unit_of_work:
            now_ms = self._now_ms()
            receipt = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if receipt is not None:
                if receipt.request_hash != command.request_hash:
                    return _current(unit_of_work, command, ResultCode.DUPLICATE_COMMAND)
                if (
                    receipt.response_json is not None
                    and receipt.status is not CommandReceiptStatus.RECEIVED
                ):
                    return ExpireApprovalResult(**loads(receipt.response_json))
                raise RuntimeError("RECEIVED ExpireApproval receipt requires reconciliation")
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="ExpireApproval",
                request_hash=command.request_hash,
                aggregate_type="Approval",
                aggregate_id=command.approval_id,
                created_at_ms=now_ms,
            )
            approval = unit_of_work.approvals.get(command.approval_id)
            if approval is None:
                raise LookupError(f"approval not found: {command.approval_id}")
            action = unit_of_work.actions.get(approval.action_id)
            if action is None:
                raise LookupError(f"action not found: {approval.action_id}")
            entry = self._registry.get_required(action.connector_id, action.tool_name)
            current_source_snapshot_hash = calculate_canonical_json_hash(
                command.current_source_snapshot
            )
            plan = load_plan_record(unit_of_work.plans, action.plan_id)
            if plan is None:
                raise LookupError(f"plan not found: {action.plan_id}")
            current = tuple(
                candidate
                for candidate in current_plan_tuple(unit_of_work.plans, plan.run_id)
                if candidate.status is not PlanStatusV1.SUPERSEDED
            )
            if action.version != command.expected_action_version:
                result = _current(unit_of_work, command, ResultCode.VERSION_CONFLICT)
            else:
                next_action, next_approval = transition_expire_approval(
                    ApprovalExpiryInput(
                        action_status=ActionStatusV1(action.status),
                        action_version=action.version,
                        current_arguments_hash=action.arguments_hash,
                        approval_status=approval.status,
                        approval_action_version=approval.action_version,
                        approval_arguments_hash=approval.canonical_arguments_hash,
                        approval_source_snapshot_hash=approval.source_snapshot_hash,
                        current_source_snapshot_hash=current_source_snapshot_hash,
                        approval_policy_version=approval.policy_version,
                        current_policy_version=entry.registry_version,
                        approval_tool_schema_version=approval.tool_schema_version,
                        current_tool_schema_version=entry.input_schema_version,
                        expires_at_ms=approval.expires_at_ms,
                        now_ms=now_ms,
                        plan_status=plan.status,
                        plan_is_current=len(current) == 1 and current[0].id == plan.id,
                    )
                )
                if not update_approval_status(
                    unit_of_work,
                    approval.id,
                    expected_status=approval.status,
                    next_status=next_approval,
                ):
                    raise RuntimeError("validated ExpireApproval Approval CAS failed")
                updated = update_action_record(
                    unit_of_work,
                    action.id,
                    expected_version=action.version,
                    expected_status=ActionStatusV1(action.status),
                    next_status=next_action,
                    updated_at_ms=now_ms,
                )
                if updated is None:
                    raise RuntimeError("validated ExpireApproval Action CAS failed")
                result = ExpireApprovalResult(
                    True,
                    ResultCode.TRANSITION_APPLIED.value,
                    approval.id,
                    next_approval.value,
                    action.id,
                    next_action.value,
                    updated.version,
                )
                for event_type in ("ACTION_EXPIRED", "APPROVAL_EXPIRED"):
                    unit_of_work.audits.append(
                        AuditEvent(
                            account_id=approval.approved_by_account_id,
                            run_id=plan.run_id,
                            action_id=action.id,
                            actor_type="SYSTEM",
                            actor_id="expire_approval",
                            actor_display="ExpireApproval",
                            event_type=event_type,
                            outcome=ResultCode.TRANSITION_APPLIED.value,
                            metadata_json=dumps(
                                {
                                    "command_id": command.command_id,
                                    "approval_id": approval.id,
                                },
                                sort_keys=True,
                            ),
                            created_at_ms=now_ms,
                        )
                    )
            unit_of_work.command_receipts.store_result(
                command_id=command.command_id,
                applied=result.applied,
                result_code=ResultCode(result.result_code),
                result_version=result.action_version,
                response_json=dumps(asdict(result), sort_keys=True),
                completed_at_ms=now_ms,
            )
            unit_of_work.commit()
            return result


def _current(
    unit_of_work: UnitOfWork,
    command: ExpireApprovalCommand,
    code: ResultCode,
) -> ExpireApprovalResult:
    approval = unit_of_work.approvals.get(command.approval_id)
    if approval is None:
        raise LookupError(f"approval not found: {command.approval_id}")
    action = unit_of_work.actions.get(approval.action_id)
    if action is None:
        raise LookupError(f"action not found: {approval.action_id}")
    return ExpireApprovalResult(
        False,
        code.value,
        approval.id,
        approval.status.value,
        action.id,
        action.status,
        action.version,
        "command conflict",
    )


__all__ = ["ExpireApprovalCommand", "ExpireApprovalHandler", "ExpireApprovalResult"]
