"""Canonical persisted Application authority for Action rejection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from json import dumps, loads
from re import fullmatch

from google_work_agent.application.projections import build_snapshot_required_event
from google_work_agent.application.write_persistence import emit_command_rejected_hash_mismatch
from google_work_agent.domain import ActionStatus, EffectType, ResultCode, next_allowed_action_commands
from google_work_agent.domain.action.transitions.reject_action import transition_reject_action
from google_work_agent.ports import (
    ActionRecord,
    AuditEventRecord,
    CommandReceiptRecord,
    CommandReceiptStatus,
    PlanStatus,
    RunEventPublisher,
    TraceEventRecord,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class RejectActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class RejectActionResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    request_replayed: bool = False
    conflict_detail: str | None = None


class RejectActionHandler:
    """Persist rejection, revoke approval authority, block dependents, and terminalize parents."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        event_publisher: RunEventPublisher | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._event_publisher = event_publisher

    def __call__(self, command: RejectActionCommand) -> RejectActionResult:
        if command.reason_code is not None and fullmatch(r"[A-Z][A-Z0-9_]{0,127}", command.reason_code) is None:
            raise ValueError("reason_code must be a safe uppercase identifier")
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._resolve_existing_receipt(unit_of_work, existing, command)
            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="RejectAction",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = self._require_action(unit_of_work, command.action_id)
            plan = unit_of_work.plans.get_by_id(action.plan_id)
            if plan is None:
                raise LookupError(f"plan not found: {action.plan_id}")
            run = unit_of_work.runs.get_by_id(plan.run_id)
            if run is None:
                raise LookupError(f"run not found: {plan.run_id}")
            conversation = unit_of_work.conversations.get_by_id(run.conversation_id)
            if conversation is None:
                raise LookupError(f"conversation not found: {run.conversation_id}")
            actor_account_id = conversation.account_id

            preview = transition_reject_action(
                ActionStatus(action.status), action.version, command.expected_version,
                effect_type=EffectType(action.effect_type),
            )
            revoked_approval_ids: tuple[str, ...] = ()
            if preview.applied:
                revoked_approval_ids = unit_of_work.approvals.revoke_active_by_action(action.id)
            result = unit_of_work.actions.reject_write(
                action.id, expected_version=command.expected_version, updated_at_ms=now_ms
            )
            response = RejectActionResult(
                applied=result.applied,
                result_code=result.result_code.value,
                action_id=action.id,
                action_status=result.current_status.value,
                action_version=result.current_version,
                next_allowed_commands=tuple(
                    item.value for item in next_allowed_action_commands(
                        result.current_status, effect_type=EffectType(action.effect_type)
                    )
                ),
                conflict_detail=result.conflict_detail,
            )
            if result.applied:
                blocked = self._block_dependents(
                    unit_of_work=unit_of_work,
                    rejected_action_id=action.id,
                    run_id=run.id,
                    command_id=command.command_id,
                    actor_account_id=actor_account_id,
                    now_ms=now_ms,
                )
                metadata: dict[str, object] = {
                    "plan_id": plan.id,
                    "action_id": action.id,
                    "command_id": command.command_id,
                    "previous_status": action.status,
                    "new_status": result.current_status.value,
                    "reason_present": command.reason_code is not None,
                    "revoked_approval_ids": list(revoked_approval_ids),
                    "blocked_dependent_action_ids": list(blocked),
                }
                if command.reason_code is not None:
                    metadata["reason_code"] = command.reason_code
                unit_of_work.traces.add(TraceEventRecord(
                    run_id=run.id, action_id=action.id, event_type="ACTION_REJECTED",
                    status=result.current_status.value, duration_ms=None,
                    payload_json=dumps({"command_id": command.command_id}, sort_keys=True),
                    created_at_ms=now_ms,
                ))
                unit_of_work.audits.add(self._audit_event(
                    run_id=run.id, action_id=action.id, actor_account_id=actor_account_id,
                    event_type="ACTION_REJECTED", metadata=metadata, created_at_ms=now_ms,
                ))
                terminal = {
                    ActionStatus.REJECTED.value, ActionStatus.VERIFIED.value,
                    ActionStatus.FAILED.value, ActionStatus.BLOCKED.value,
                    ActionStatus.DEPENDENCY_BLOCKED.value, ActionStatus.MISMATCH.value,
                    ActionStatus.CANCELLED.value,
                }
                current_actions = unit_of_work.actions.list_by_plan(plan.id)
                if current_actions and all(item.status in terminal for item in current_actions):
                    if plan.status in {PlanStatus.WAITING_APPROVAL, PlanStatus.ACTIVE}:
                        unit_of_work.plans.complete(plan.id)
                    completed = unit_of_work.runs.finalize_action_outcomes(
                        run.id, expected_version=run.version, finished_at_ms=now_ms
                    )
                    if not completed.applied:
                        raise RuntimeError(f"reject terminal finalization failed: {completed.result_code.value}")
            response = self._finish(unit_of_work, command, response, now_ms)
            if response.applied and self._event_publisher is not None:
                self._event_publisher.publish(
                    build_snapshot_required_event(
                        run_id=run.id,
                        occurred_at_ms=now_ms,
                        reason="ACTION_REJECTED",
                    )
                )
            return response

    def _resolve_existing_receipt(self, unit_of_work: UnitOfWork, receipt: CommandReceiptRecord, command: RejectActionCommand) -> RejectActionResult:
        if receipt.request_hash != command.request_hash:
            emit_command_rejected_hash_mismatch(
                unit_of_work=unit_of_work, receipt=receipt, run_id=None,
                action_id=command.action_id, now_ms=self._now_ms(),
            )
            action = unit_of_work.actions.get_by_id(command.action_id)
            if action is None:
                return RejectActionResult(False, ResultCode.DUPLICATE_COMMAND.value, command.action_id, "UNKNOWN", receipt.result_version or 0, (), True, "command_id already exists with a different request_hash")
            return replace(self._result(action, ResultCode.DUPLICATE_COMMAND, "command_id already exists with a different request_hash"), request_replayed=True)
        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            raise RuntimeError("RECEIVED receipt recovery requires aggregate-specific handling")
        payload = loads(receipt.response_json)
        if not isinstance(payload, dict):
            raise RuntimeError("reject receipt response must be an object")
        payload.setdefault("request_replayed", False)
        payload["next_allowed_commands"] = tuple(payload["next_allowed_commands"])
        return replace(RejectActionResult(**payload), request_replayed=True)

    @staticmethod
    def _finish(unit_of_work: UnitOfWork, command: RejectActionCommand, response: RejectActionResult, now_ms: int) -> RejectActionResult:
        unit_of_work.command_receipts.finish_json(
            command_id=command.command_id, applied=response.applied,
            result_code=ResultCode(response.result_code), result_version=response.action_version,
            response_json=dumps(asdict(response), sort_keys=True), completed_at_ms=now_ms,
        )
        unit_of_work.commit()
        return response

    @staticmethod
    def _result(action: ActionRecord, result_code: ResultCode, conflict_detail: str | None) -> RejectActionResult:
        return RejectActionResult(
            False, result_code.value, action.id, action.status, action.version,
            tuple(item.value for item in next_allowed_action_commands(ActionStatus(action.status), effect_type=EffectType(action.effect_type))),
            conflict_detail=conflict_detail,
        )

    @staticmethod
    def _audit_event(*, run_id: str, action_id: str, actor_account_id: str, event_type: str, metadata: dict[str, object], created_at_ms: int) -> AuditEventRecord:
        return AuditEventRecord(
            account_id=actor_account_id, run_id=run_id, action_id=action_id,
            actor_type="USER", actor_id=actor_account_id, actor_display=None,
            event_type=event_type, outcome=ResultCode.TRANSITION_APPLIED.value,
            metadata_json=dumps(metadata, sort_keys=True), created_at_ms=created_at_ms,
        )

    @classmethod
    def _block_dependents(cls, *, unit_of_work: UnitOfWork, rejected_action_id: str, run_id: str, command_id: str, actor_account_id: str, now_ms: int) -> tuple[str, ...]:
        blocked: list[str] = []
        pending = list(unit_of_work.action_dependencies.list_dependents(rejected_action_id))
        visited: set[str] = set()
        while pending:
            dependent_id = pending.pop(0)
            if dependent_id in visited:
                continue
            visited.add(dependent_id)
            dependent = unit_of_work.actions.get_by_id(dependent_id)
            if dependent is None or dependent.status not in {ActionStatus.PROPOSED.value, ActionStatus.MODIFIED.value, ActionStatus.APPROVED.value}:
                continue
            revoked = unit_of_work.approvals.revoke_active_by_action(dependent_id)
            if not unit_of_work.actions.mark_dependency_blocked(dependent_id, updated_at_ms=now_ms):
                raise RuntimeError(f"dependency block transition failed: {dependent_id}")
            blocked.append(dependent_id)
            metadata = {
                "command_id": command_id, "blocked_by_action_id": rejected_action_id,
                "previous_status": dependent.status, "new_status": ActionStatus.DEPENDENCY_BLOCKED.value,
                "revoked_approval_ids": list(revoked),
            }
            unit_of_work.traces.add(TraceEventRecord(
                run_id=run_id, action_id=dependent_id, event_type="ACTION_DEPENDENCY_BLOCKED",
                status=ActionStatus.DEPENDENCY_BLOCKED.value, duration_ms=None,
                payload_json=dumps({"command_id": command_id, "blocked_by_action_id": rejected_action_id}, sort_keys=True),
                created_at_ms=now_ms,
            ))
            unit_of_work.audits.add(cls._audit_event(
                run_id=run_id, action_id=dependent_id, actor_account_id=actor_account_id,
                event_type="ACTION_DEPENDENCY_BLOCKED", metadata=metadata, created_at_ms=now_ms,
            ))
            pending.extend(unit_of_work.action_dependencies.list_dependents(dependent_id))
        return tuple(blocked)

    @staticmethod
    def _require_action(unit_of_work: UnitOfWork, action_id: str) -> ActionRecord:
        action = unit_of_work.actions.get_by_id(action_id)
        if action is None:
            raise LookupError(f"action not found: {action_id}")
        return action
