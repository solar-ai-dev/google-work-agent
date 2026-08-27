"""Canonical persisted FinalizeCancel application boundary."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps
from types import SimpleNamespace

from google_work_agent.application.cancel_intent import has_durable_cancel_intent
from google_work_agent.application.persistence_cas import update_plan_record
from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryCommand,
    RequireRecoveryHandler,
)
from google_work_agent.application.write_cancellation import _apply_run_transition
from google_work_agent.application.write_cancellation_contracts import (
    FinalizeRunCancellationCommand,
)
from google_work_agent.application.write_execution_contracts import WriteRunResponse
from google_work_agent.application.write_persistence import (
    audit_event,
    cancel_pending_actions,
    finish_json_receipt,
    require_run,
    resolve_existing_run_receipt,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.domain.run.transitions.finalize_cancel import transition_finalize_cancel
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import UnitOfWork
from google_work_agent.ports.persistence.execution_attempt_repository import active_attempt_tuple
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple

FinalizeCancelCommand = FinalizeRunCancellationCommand
FinalizeCancelResult = WriteRunResponse


class FinalizeCancelHandler:
    """Finalize durable cancel intent after all child facts are settled."""

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: FinalizeCancelCommand) -> FinalizeCancelResult:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return resolve_existing_run_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    run_id=command.run_id,
                    now_ms=self._now_ms(),
                )
            now_ms = self._now_ms()
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="FinalizeRunCancellation",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            run = require_run(unit_of_work, command.run_id)
            plans = current_plan_tuple(unit_of_work.plans, run.id)
            plan = max(
                plans,
                key=lambda item: (item.revision_no, item.created_at_ms),
                default=None,
            )
            actions = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)
            if command.expected_run_version != run.version:
                response = WriteRunResponse(
                    applied=False,
                    result_code=ResultCode.VERSION_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=None if plan is None else plan.id,
                    plan_status=None if plan is None else plan.status.value,
                    conflict_detail="expected_run_version does not match current version",
                )
                finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
                unit_of_work.commit()
                return response
            finalize_expected_version = command.expected_run_version
            if run.status is RunStatusV1.VERIFYING:
                if not _has_cancel_intent(unit_of_work, run.id):
                    response = WriteRunResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        run_id=run.id,
                        run_status=run.status.value,
                        run_version=run.version,
                        plan_id=None if plan is None else plan.id,
                        plan_status=None if plan is None else plan.status.value,
                        conflict_detail=(
                            "verification can continue cancellation only after a successful "
                            "cancel request"
                        ),
                    )
                    finish_json_receipt(
                        unit_of_work, command.command_id, response, run.version, now_ms
                    )
                    unit_of_work.commit()
                    return response
            elif run.status not in {
                RunStatusV1.CANCEL_REQUESTED,
                RunStatusV1.REAUTH_REQUIRED,
            }:
                response = WriteRunResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=None if plan is None else plan.id,
                    plan_status=None if plan is None else plan.status.value,
                    conflict_detail="cancellation finalization requires cancel-requested state",
                )
                finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
                unit_of_work.commit()
                return response
            if any(action.status == ActionStatusV1.UNKNOWN_RESULT.value for action in actions):
                unknown_action = next(
                    action
                    for action in actions
                    if action.status == ActionStatusV1.UNKNOWN_RESULT.value
                )
                unknown_attempt = next(
                    attempt
                    for approval in unit_of_work.approval_history.list_for_action(
                        unknown_action.id
                    )
                    for attempt in active_attempt_tuple(
                        unit_of_work.execution_attempts, approval.id
                    )
                    if attempt.status.value == "UNKNOWN_RESULT"
                )
                recovery_payload = {
                    "run_id": run.id,
                    "expected_version": run.version,
                    "reason": "UNKNOWN_RESULT",
                    "scope": "ACTION",
                    "action_id": unknown_action.id,
                    "execution_attempt_id": unknown_attempt.id,
                    "attempt_version": unknown_attempt.version,
                }
                recovery_run = RequireRecoveryHandler.apply_in_unit_of_work(
                    unit_of_work,
                    RequireRecoveryCommand(
                        run_id=run.id,
                        expected_version=run.version,
                        command_id=(
                            f"system:finalize-cancel-require-recovery:{command.command_id}"
                        ),
                        request_hash=calculate_canonical_json_hash(recovery_payload),
                        reason="UNKNOWN_RESULT",
                        scope="ACTION",
                        recovery_fingerprint=calculate_canonical_json_hash(
                            {
                                "action_id": unknown_action.id,
                                "action_version": unknown_action.version,
                                "attempt_id": unknown_attempt.id,
                                "attempt_version": unknown_attempt.version,
                            }
                        ),
                        action_id=unknown_action.id,
                        execution_attempt_id=unknown_attempt.id,
                    ),
                    now_ms=now_ms,
                )
                response = WriteRunResponse(
                    applied=False,
                    result_code=ResultCode.RECOVERY_REQUIRED.value,
                    run_id=run.id,
                    run_status=recovery_run.current_status,
                    run_version=recovery_run.current_version,
                    plan_id=None if plan is None else plan.id,
                    plan_status=None if plan is None else plan.status.value,
                    result_kind="RECOVERY_REQUIRED",
                    conflict_detail="unknown write results must be resolved before cancellation",
                )
            elif any(action.status == ActionStatusV1.EXECUTING.value for action in actions):
                response = WriteRunResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=None if plan is None else plan.id,
                    plan_status=None if plan is None else plan.status.value,
                    conflict_detail="cannot finalize cancellation while write is executing",
                )
            elif any(action.status == ActionStatusV1.EXECUTED.value for action in actions):
                response = WriteRunResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=None if plan is None else plan.id,
                    plan_status=None if plan is None else plan.status.value,
                    conflict_detail=(
                        "cannot finalize cancellation while an executed write awaits verification"
                    ),
                )
            else:
                if plan is not None:
                    cancel_pending_actions(
                        unit_of_work=unit_of_work,
                        run_id=run.id,
                        plan_id=plan.id,
                        updated_at_ms=now_ms,
                    )
                    actions = unit_of_work.actions.list_for_plan(plan.id)
                    if (
                        update_plan_record(
                            unit_of_work,
                            plan.id,
                            expected_status=plan.status,
                            next_status=PlanStatusV1.CANCELLED,
                        )
                        is None
                    ):
                        raise RuntimeError(
                            f"validated Plan cancellation CAS failed: {plan.id}"
                        )
                    plan = max(
                        current_plan_tuple(unit_of_work.plans, run.id),
                        key=lambda item: (item.revision_no, item.created_at_ms),
                    )
                final_result = _apply_run_transition(
                    unit_of_work,
                    SimpleNamespace(
                        id=run.id, status=run.status, version=finalize_expected_version
                    ),
                    finalize_expected_version,
                    _finalize_transition(
                        unit_of_work=unit_of_work,
                        run_id=run.id,
                        plan=plan,
                        actions=actions,
                    ),
                    finished_at_ms=now_ms,
                )
                if not final_result.applied:
                    raise RuntimeError("validated cancellation finalization was not applied")
                response = WriteRunResponse(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED.value,
                    run_id=run.id,
                    run_status=final_result.current_status.value,
                    run_version=final_result.current_version,
                    plan_id=None if plan is None else plan.id,
                    plan_status=None if plan is None else PlanStatusV1.CANCELLED.value,
                    result_kind=(
                        "PARTIAL"
                        if any(action.status == ActionStatusV1.VERIFIED.value for action in actions)
                        else "CANCELLED"
                    ),
                )
            if response.applied and response.run_status == RunStatusV1.CANCELLED.value:
                unit_of_work.traces.append(
                    TraceEventRecord(
                        run_id=run.id,
                        action_id=None,
                        event_type="RUN_CANCELLED",
                        status=response.run_status,
                        duration_ms=None,
                        payload_json=dumps({"result_kind": response.result_kind}, sort_keys=True),
                        created_at_ms=now_ms,
                    )
                )
                unit_of_work.audits.append(
                    audit_event(
                        run_id=run.id,
                        action_id=None,
                        event_type="RUN_CANCELLED",
                        outcome=response.result_code,
                        metadata={"result_kind": response.result_kind},
                        created_at_ms=now_ms,
                    )
                )
            finish_json_receipt(
                unit_of_work, command.command_id, response, response.run_version, now_ms
            )
            unit_of_work.commit()
            return response


def _has_cancel_intent(unit_of_work: UnitOfWork, run_id: str) -> bool:
    return has_durable_cancel_intent(unit_of_work.cancel_intents, run_id)


def _finalize_transition(
    *, unit_of_work: UnitOfWork, run_id: str, plan: object | None, actions: tuple[object, ...]
) -> Callable[[RunStatusV1], RunStatusV1]:
    current_plans = tuple(
        candidate
        for candidate in current_plan_tuple(unit_of_work.plans, run_id)
        if candidate.status is not PlanStatusV1.SUPERSEDED
    )
    approvals = tuple(
        approval
        for action in actions
        for approval in unit_of_work.approval_history.list_for_action(action.id)
    )
    attempts = tuple(
        attempt
        for approval in approvals
        for attempt in active_attempt_tuple(unit_of_work.execution_attempts, approval.id)
    )

    def apply(current_status: RunStatusV1) -> RunStatusV1:
        return transition_finalize_cancel(
            current_status,
            cancel_intent_active=_has_cancel_intent(unit_of_work, run_id),
            plan_status=None if plan is None else plan.status,
            plan_is_current=(
                not current_plans
                if plan is None
                else len(current_plans) == 1 and current_plans[0].id == plan.id
            ),
            action_statuses=tuple(ActionStatusV1(action.status) for action in actions),
            approval_statuses=tuple(approval.status for approval in approvals),
            attempt_statuses=tuple(attempt.status for attempt in attempts),
        )

    return apply


__all__ = ["FinalizeCancelCommand", "FinalizeCancelHandler", "FinalizeCancelResult"]
