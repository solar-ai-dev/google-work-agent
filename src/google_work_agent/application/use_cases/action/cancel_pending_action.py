"""Persist one canonical CancelPendingAction command in a short UoW."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads

from google_work_agent.application.use_cases.action.persistence_cas import (
    update_action_record,
    update_approval_status,
)
from google_work_agent.domain.action.model import ActionCommand, ActionStatusV1, EffectType
from google_work_agent.domain.action.transitions.cancel_pending_action import (
    transition_cancel_pending_action,
)
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.audit_event.model import AuditEvent
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.ports.events.observability_events import sanitize_event_attributes
from google_work_agent.ports.persistence.approval_repository import active_approval_tuple
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class CancelPendingActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class CancelPendingActionResult:
    applied: bool
    result_code: ResultCode
    current_status: ActionStatusV1
    current_version: int
    next_allowed_commands: tuple[ActionCommand, ...]
    conflict_detail: str | None = None
    request_replayed: bool = False


class CancelPendingActionHandler:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: CancelPendingActionCommand) -> CancelPendingActionResult:
        with self._unit_of_work_factory() as unit_of_work:
            result = self.apply_in_unit_of_work(unit_of_work, command, now_ms=self._now_ms())
            unit_of_work.commit()
            return result

    @staticmethod
    def apply_in_unit_of_work(
        unit_of_work: UnitOfWork,
        command: CancelPendingActionCommand,
        *,
        now_ms: int,
    ) -> CancelPendingActionResult:
        existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
        if existing is not None:
            return CancelPendingActionHandler._replay(unit_of_work, command, existing)
        unit_of_work.command_receipts.reserve_or_replay(
            command_id=command.command_id,
            command_type="CancelPendingAction",
            request_hash=command.request_hash,
            aggregate_type="Action",
            aggregate_id=command.action_id,
            created_at_ms=now_ms,
        )
        action = unit_of_work.actions.get(command.action_id)
        if action is None:
            raise LookupError(f"action not found: {command.action_id}")
        plan = unit_of_work.plans.load_bundle(action.plan_id)
        if plan is None:
            raise LookupError(f"plan not found: {action.plan_id}")
        current_plan = max(
            current_plan_tuple(unit_of_work.plans, plan.run_id),
            key=lambda candidate: candidate.revision_no,
            default=None,
        )
        decision = transition_cancel_pending_action(
            ActionStatusV1(action.status),
            action.version,
            command.expected_version,
            effect_type=EffectType(action.effect_type),
            plan_status=PlanStatusV1(plan.status),
            plan_is_current=current_plan is not None and current_plan.id == plan.id,
        )
        revoked_ids: list[str] = []
        if decision.applied:
            for approval in active_approval_tuple(unit_of_work.approvals, action.id):
                if approval.status is not ApprovalStatusV1.ACTIVE:
                    continue
                if not update_approval_status(
                    unit_of_work,
                    approval.id,
                    expected_status=approval.status,
                    next_status=ApprovalStatusV1.REVOKED,
                ):
                    raise RuntimeError(f"validated Approval revoke CAS failed: {approval.id}")
                revoked_ids.append(approval.id)
                unit_of_work.audits.append(
                    _audit_event(
                        run_id=plan.run_id,
                        action_id=action.id,
                        event_type="APPROVAL_REVOKED",
                        outcome=ResultCode.TRANSITION_APPLIED.value,
                        metadata={"approval_id": approval.id, "command_id": command.command_id},
                        created_at_ms=now_ms,
                    )
                )
            if (
                update_action_record(
                    unit_of_work,
                    action.id,
                    expected_version=action.version,
                    expected_status=ActionStatusV1(action.status),
                    next_status=decision.current_status,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError("validated CancelPendingAction CAS failed")
            unit_of_work.audits.append(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="ACTION_CANCELLED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={
                        "command_id": command.command_id,
                        "previous_status": ActionStatusV1(action.status).value,
                        "revoked_approval_ids": revoked_ids,
                    },
                    created_at_ms=now_ms,
                )
            )
        result = CancelPendingActionResult(
            decision.applied,
            decision.result_code,
            decision.current_status,
            decision.current_version,
            decision.next_allowed_commands,
            decision.conflict_detail,
        )
        CancelPendingActionHandler._finish(unit_of_work, command.command_id, result, now_ms)
        return result

    @staticmethod
    def _finish(
        unit_of_work: UnitOfWork,
        command_id: str,
        result: CancelPendingActionResult,
        now_ms: int,
    ) -> None:
        payload = asdict(result)
        payload["result_code"] = result.result_code.value
        payload["current_status"] = result.current_status.value
        payload["next_allowed_commands"] = [item.value for item in result.next_allowed_commands]
        unit_of_work.command_receipts.store_result(
            command_id=command_id,
            applied=result.applied,
            result_code=result.result_code,
            result_version=result.current_version,
            response_json=dumps(payload, sort_keys=True),
            completed_at_ms=now_ms,
        )

    @staticmethod
    def _replay(
        unit_of_work: UnitOfWork,
        command: CancelPendingActionCommand,
        receipt: object,
    ) -> CancelPendingActionResult:
        action = unit_of_work.actions.get(command.action_id)
        if action is None:
            raise LookupError(f"action not found: {command.action_id}")
        if receipt.request_hash != command.request_hash:
            return CancelPendingActionResult(
                False,
                ResultCode.DUPLICATE_COMMAND,
                ActionStatusV1(action.status),
                action.version,
                (),
                "command_id already exists with a different request_hash",
                True,
            )
        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            raise RuntimeError("RECEIVED CancelPendingAction receipt requires transaction recovery")
        payload = loads(receipt.response_json)
        return CancelPendingActionResult(
            applied=bool(payload["applied"]),
            result_code=ResultCode(payload["result_code"]),
            current_status=ActionStatusV1(payload["current_status"]),
            current_version=int(payload["current_version"]),
            next_allowed_commands=tuple(
                ActionCommand(item) for item in payload.get("next_allowed_commands", ())
            ),
            conflict_detail=payload.get("conflict_detail"),
            request_replayed=True,
        )


__all__ = [
    "CancelPendingActionCommand",
    "CancelPendingActionHandler",
    "CancelPendingActionResult",
]


def _audit_event(
    *,
    run_id: str,
    action_id: str,
    event_type: str,
    outcome: str,
    metadata: dict[str, object],
    created_at_ms: int,
) -> AuditEvent:
    return AuditEvent(
        account_id=None,
        run_id=run_id,
        action_id=action_id,
        actor_type="SYSTEM",
        actor_id="cancel_pending_action",
        actor_display="CancelPendingAction",
        event_type=event_type,
        outcome=outcome,
        metadata_json=dumps(sanitize_event_attributes(metadata).values, sort_keys=True),
        created_at_ms=created_at_ms,
    )
