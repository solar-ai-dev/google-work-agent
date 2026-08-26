"""Aggregate-safe CompleteWriteRun application boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from json import dumps
from typing import cast

from google_work_agent.application.cancel_intent import (
    CancelIntentReceiptReader,
    has_durable_cancel_intent,
)
from google_work_agent.application.run_terminal import (
    RunTransitionResponse,
    _finish_json_receipt,
    _handle_existing_receipt,
    _require_conversation,
    _require_run,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.approval.model import ApprovalStatus
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatus
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanStatus
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import Run as RunRecord
from google_work_agent.domain.run.model import RunStatus, next_allowed_run_commands
from google_work_agent.domain.run.transitions.complete_write_run import (
    transition_complete_write_run,
)
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.domain.verification.model import VerificationStatus
from google_work_agent.ports import (
    UnitOfWork,
)


@dataclass(frozen=True, slots=True)
class CompleteWriteRunCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_version: int


_UNRESOLVED_ATTEMPT_STATUSES = frozenset(
    {
        ExecutionAttemptStatus.CLAIMED,
        ExecutionAttemptStatus.EXECUTING,
        ExecutionAttemptStatus.UNKNOWN_RESULT,
    }
)


class CompleteWriteRunService:
    """Complete a write Run only after aggregate invariants hold in one UoW.

    The caller may use prechecks as an optimization, but this service is the
    application authority. MISMATCH and partial outcomes are deliberately not
    accepted here; they must pass through a registered recovery/finalization
    command instead.
    """

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: CompleteWriteRunCommand) -> RunTransitionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            completed_at_ms = self._now_ms()
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _handle_existing_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    run_id=command.run_id,
                    target_status=RunStatus.COMPLETED,
                    reason_code="WRITE_VERIFIED",
                    completed_at_ms=completed_at_ms,
                )

            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="CompleteWriteRun",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=completed_at_ms,
            )
            run = _require_run(unit_of_work, command.run_id)
            conversation = _require_conversation(unit_of_work, run.conversation_id)
            relevant_plans = tuple(
                plan
                for plan in unit_of_work.plans.list_by_run(run.id)
                if plan.status is not PlanStatus.SUPERSEDED
            )
            plan = relevant_plans[0] if len(relevant_plans) == 1 else None
            actions = () if plan is None else unit_of_work.actions.list_by_plan(plan.id)
            cancel_reader = cast(CancelIntentReceiptReader, unit_of_work.command_receipts)

            conflict_detail = self._aggregate_conflict(
                unit_of_work=unit_of_work,
                run_id=run.id,
                relevant_plans=relevant_plans,
                plan=plan,
                actions=actions,
                cancel_reader=cancel_reader,
            )
            if conflict_detail is not None:
                return self._reject(
                    unit_of_work=unit_of_work,
                    command=command,
                    run=run,
                    completed_at_ms=completed_at_ms,
                    conflict_detail=conflict_detail,
                )

            assert plan is not None
            if run.version != command.expected_version:
                return self._reject(
                    unit_of_work=unit_of_work,
                    command=command,
                    run=run,
                    completed_at_ms=completed_at_ms,
                    conflict_detail="expected_version does not match current_version",
                )
            next_status = transition_complete_write_run(run.status)
            if not unit_of_work.runs.update_if_version_and_status(
                run.id,
                run.version,
                frozenset({run.status}),
                {
                    "status": next_status.value,
                    "version": run.version + 1,
                    "finished_at_ms": completed_at_ms,
                },
            ):
                raise RuntimeError("validated CompleteWriteRun CAS failed")
            response = RunTransitionResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                run_id=run.id,
                run_status=next_status.value,
                run_version=run.version + 1,
                next_allowed_commands=(),
                reason_code="WRITE_VERIFIED",
                result_kind=next_status.value,
                conflict_detail=None,
            )
            if response.applied:
                if (
                    unit_of_work.plans.update_if_status(
                        plan.id, expected_status=plan.status, next_status=PlanStatus.COMPLETED
                    )
                    is None
                ):
                    raise RuntimeError(f"validated Plan completion CAS failed: {plan.id}")
                unit_of_work.traces.add(
                    TraceEventRecord(
                        run_id=run.id,
                        action_id=None,
                        event_type="RUN_COMPLETED",
                        status=next_status.value,
                        duration_ms=None,
                        payload_json=dumps(
                            {
                                "command_id": command.command_id,
                                "command_type": "CompleteWriteRun",
                                "reason_code": "WRITE_VERIFIED",
                            },
                            sort_keys=True,
                        ),
                        created_at_ms=completed_at_ms,
                    )
                )
                unit_of_work.audits.add(
                    AuditEventRecord(
                        account_id=conversation.account_id,
                        run_id=run.id,
                        action_id=None,
                        actor_type="AGENT",
                        actor_id="complete_write_run",
                        actor_display="CompleteWriteRun",
                        event_type="RUN_COMPLETED",
                        outcome=ResultCode.TRANSITION_APPLIED.value,
                        metadata_json=dumps(
                            {"command_id": command.command_id, "reason_code": "WRITE_VERIFIED"},
                            sort_keys=True,
                        ),
                        created_at_ms=completed_at_ms,
                    )
                )
            _finish_json_receipt(
                unit_of_work=unit_of_work,
                command_id=command.command_id,
                response=response,
                completed_at_ms=completed_at_ms,
            )
            unit_of_work.commit()
            return response

    @staticmethod
    def _aggregate_conflict(
        *,
        unit_of_work: UnitOfWork,
        run_id: str,
        relevant_plans: tuple[PlanRecord, ...],
        plan: PlanRecord | None,
        actions: tuple[ActionRecord, ...],
        cancel_reader: CancelIntentReceiptReader,
    ) -> str | None:
        if has_durable_cancel_intent(cancel_reader, run_id):
            return "durable cancel intent forbids CompleteWriteRun"
        if len(relevant_plans) != 1 or plan is None:
            return "write completion requires exactly one non-superseded plan"
        if plan.run_id != run_id:
            return "non-superseded plan does not belong to the run"
        if plan.status is not PlanStatus.ACTIVE:
            return "write completion requires the non-superseded plan to be ACTIVE"
        if not actions:
            return "write completion requires persisted actions"

        for action in actions:
            if action.plan_id != plan.id:
                return f"action {action.id} does not belong to the active plan"
            status = ActionStatus(action.status)
            if status is ActionStatus.UNKNOWN_RESULT:
                return "UNKNOWN_RESULT must be resolved through Recovery before completion"
            if status is ActionStatus.EXECUTED:
                return "EXECUTED action must be verified before completion"
            if status is ActionStatus.MISMATCH:
                return "MISMATCH requires a registered Recovery resolution"
            if status is not ActionStatus.VERIFIED:
                return f"action {action.id} is not VERIFIED"

            approvals = unit_of_work.approvals.list_by_action(action.id)
            if any(approval.status is ApprovalStatus.ACTIVE for approval in approvals):
                return f"action {action.id} has an illegal ACTIVE approval"

            attempts = tuple(
                attempt
                for approval in approvals
                for attempt in unit_of_work.execution_attempts.list_by_approval(approval.id)
            )
            if any(attempt.status in _UNRESOLVED_ATTEMPT_STATUSES for attempt in attempts):
                return f"action {action.id} has an unresolved execution attempt"
            succeeded = tuple(
                attempt
                for attempt in attempts
                if attempt.status is ExecutionAttemptStatus.SUCCEEDED
            )
            if not succeeded:
                return f"action {action.id} has no successful execution attempt"
            latest_attempt = max(
                succeeded,
                key=lambda item: (item.attempt_no, item.started_at_ms),
            )
            verifications = unit_of_work.verifications.list_by_attempt(latest_attempt.id)
            if not verifications:
                return f"action {action.id} has no verification result"
            latest_verification = max(
                verifications,
                key=lambda item: (item.verification_no, item.verified_at_ms),
            )
            if latest_verification.status is not VerificationStatus.VERIFIED:
                return f"action {action.id} verification is unresolved"
        return None

    @staticmethod
    def _reject(
        *,
        unit_of_work: UnitOfWork,
        command: CompleteWriteRunCommand,
        run: RunRecord,
        completed_at_ms: int,
        conflict_detail: str,
    ) -> RunTransitionResponse:
        response = RunTransitionResponse(
            applied=False,
            result_code=ResultCode.STATE_CONFLICT.value,
            run_id=run.id,
            run_status=run.status.value,
            run_version=run.version,
            next_allowed_commands=tuple(
                item.value for item in next_allowed_run_commands(run.status)
            ),
            reason_code="WRITE_VERIFIED",
            conflict_detail=conflict_detail,
        )
        _finish_json_receipt(
            unit_of_work=unit_of_work,
            command_id=command.command_id,
            response=response,
            completed_at_ms=completed_at_ms,
        )
        unit_of_work.commit()
        return response


__all__ = ["CompleteWriteRunService"]
