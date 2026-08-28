"""Aggregate-safe CompleteWriteRun application boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from json import dumps

from google_work_agent.application.cancel_intent import has_durable_cancel_intent
from google_work_agent.application.persistence_cas import update_plan_record
from google_work_agent.application.run_terminal import (
    RunTransitionResponse,
    _finish_json_receipt,
    _handle_existing_receipt,
    _require_conversation,
    _require_run,
)
from google_work_agent.application.use_cases.run.build_terminal_message import (
    BuildTerminalMessageHandler,
    BuildTerminalMessageQueryV1,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.message.model import Message as MessageRecord
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import Run as RunRecord
from google_work_agent.domain.run.model import RunStatusV1, next_allowed_run_commands
from google_work_agent.domain.run.transitions.complete_write_run import (
    classify_complete_write_run_result,
    transition_complete_write_run,
)
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.domain.verification.model import VerificationStatus
from google_work_agent.ports import (
    UnitOfWork,
)
from google_work_agent.ports.persistence.cancel_intent_reader import CancelIntentReader
from google_work_agent.ports.persistence.execution_attempt_repository import active_attempt_tuple
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple


@dataclass(frozen=True, slots=True)
class CompleteWriteRunCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_version: int


CompleteWriteRunResult = RunTransitionResponse


_UNRESOLVED_ATTEMPT_STATUSES = frozenset(
    {
        ExecutionAttemptStatusV1.CLAIMED,
        ExecutionAttemptStatusV1.EXECUTING,
        ExecutionAttemptStatusV1.UNKNOWN_RESULT,
    }
)


class CompleteWriteRunHandler:
    """Complete a write Run only after aggregate invariants hold in one UoW.

    The caller may use prechecks as an optimization, but this service is the
    application authority. MISMATCH and partial outcomes are deliberately not
    accepted here; they must pass through a registered recovery/finalization
    command instead.
    """

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        message_id_factory: Callable[[], str],
        build_terminal_message: BuildTerminalMessageHandler | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._message_id_factory = message_id_factory
        self._build_terminal_message = build_terminal_message or BuildTerminalMessageHandler()

    def __call__(self, command: CompleteWriteRunCommand) -> RunTransitionResponse:
        terminal_messages = {
            "SUCCESS": self._build_terminal_message(
                BuildTerminalMessageQueryV1(
                    run_id=command.run_id,
                    result_kind="SUCCESS",
                )
            ),
            "PARTIAL": self._build_terminal_message(
                BuildTerminalMessageQueryV1(
                    run_id=command.run_id,
                    result_kind="PARTIAL",
                )
            ),
        }
        with self._unit_of_work_factory() as unit_of_work:
            completed_at_ms = self._now_ms()
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _handle_existing_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    run_id=command.run_id,
                    target_status=RunStatusV1.COMPLETED,
                    reason_code="WRITE_VERIFIED",
                    completed_at_ms=completed_at_ms,
                )

            unit_of_work.command_receipts.reserve_or_replay(
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
                for plan in current_plan_tuple(unit_of_work.plans, run.id)
                if plan.status is not PlanStatusV1.SUPERSEDED
            )
            plan = relevant_plans[0] if len(relevant_plans) == 1 else None
            actions = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)
            cancel_reader = unit_of_work.cancel_intents

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
            action_statuses = tuple(ActionStatusV1(action.status) for action in actions)
            attempt_statuses = self._attempt_statuses(unit_of_work, actions)
            external_write_count = sum(
                status
                in {
                    ExecutionAttemptStatusV1.EXECUTING,
                    ExecutionAttemptStatusV1.UNKNOWN_RESULT,
                    ExecutionAttemptStatusV1.SUCCEEDED,
                    ExecutionAttemptStatusV1.FAILED,
                }
                for status in attempt_statuses
            )
            next_status = transition_complete_write_run(
                run.status,
                plan_status=plan.status,
                plan_is_current=True,
                action_statuses=action_statuses,
                attempt_statuses=attempt_statuses,
                unresolved_required_fact_count=0,
                external_write_count=external_write_count,
                cancel_intent_active=False,
            )
            result_kind = classify_complete_write_run_result(action_statuses)
            reason_code = (
                "WRITE_VERIFIED" if result_kind.value == "SUCCESS" else "WRITE_CLOSED"
            )
            if not unit_of_work.runs.update_if_version_and_status(
                run.id,
                run.version,
                frozenset({run.status}),
                {
                    "status": next_status.value,
                    "version": run.version + 1,
                    "finished_at_ms": completed_at_ms,
                    "terminal_result_kind": result_kind.value,
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
                reason_code=reason_code,
                result_kind=result_kind.value,
                conflict_detail=None,
            )
            if response.applied:
                if (
                    update_plan_record(
                        unit_of_work,
                        plan.id, expected_status=plan.status, next_status=PlanStatusV1.COMPLETED
                    )
                    is None
                ):
                    raise RuntimeError(f"validated Plan completion CAS failed: {plan.id}")
                terminal_message = terminal_messages[result_kind.value]
                message_id = self._message_id_factory()
                unit_of_work.messages.append_terminal_assistant_message(
                    MessageRecord(
                        id=message_id,
                        conversation_id=conversation.id,
                        run_id=run.id,
                        role=terminal_message.role,
                        content=terminal_message.content,
                        created_at_ms=completed_at_ms,
                    )
                )
                unit_of_work.traces.append(
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
                                "completion_mode": "WRITE",
                                "reason_code": reason_code,
                                "result_kind": result_kind.value,
                                "message_id": message_id,
                            },
                            sort_keys=True,
                        ),
                        created_at_ms=completed_at_ms,
                    )
                )
                unit_of_work.audits.append(
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
                            {
                                "command_id": command.command_id,
                                "completion_mode": "WRITE",
                                "reason_code": reason_code,
                                "result_kind": result_kind.value,
                                "message_id": message_id,
                            },
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
        cancel_reader: CancelIntentReader,
    ) -> str | None:
        if has_durable_cancel_intent(cancel_reader, run_id):
            return "durable cancel intent forbids CompleteWriteRun"
        if len(relevant_plans) != 1 or plan is None:
            return "write completion requires exactly one non-superseded plan"
        if plan.run_id != run_id:
            return "non-superseded plan does not belong to the run"
        if plan.status is not PlanStatusV1.WAITING_APPROVAL:
            return "write completion requires a WAITING_APPROVAL Write Plan"
        if not actions:
            return "write completion requires persisted actions"

        for action in actions:
            if action.plan_id != plan.id:
                return f"action {action.id} does not belong to the active plan"
            status = ActionStatusV1(action.status)
            if status is ActionStatusV1.UNKNOWN_RESULT:
                return "UNKNOWN_RESULT must be resolved through Recovery before completion"
            if status is ActionStatusV1.EXECUTED:
                return "EXECUTED action must be verified before completion"
            if status is ActionStatusV1.MISMATCH:
                return "MISMATCH requires a registered Recovery resolution"
            if status is ActionStatusV1.FAILED:
                return "FAILED Action requires retry, cancel, or recovery before completion"
            if status not in {
                ActionStatusV1.VERIFIED,
                ActionStatusV1.REJECTED,
                ActionStatusV1.CANCELLED,
                ActionStatusV1.BLOCKED,
                ActionStatusV1.DEPENDENCY_BLOCKED,
            }:
                return f"action {action.id} is not VERIFIED or otherwise closed"

            approvals = unit_of_work.approval_history.list_for_action(action.id)
            if any(approval.status is ApprovalStatusV1.ACTIVE for approval in approvals):
                return f"action {action.id} has an illegal ACTIVE approval"

            attempts = tuple(
                attempt
                for approval in approvals
                for attempt in active_attempt_tuple(unit_of_work.execution_attempts, approval.id)
            )
            if any(attempt.status in _UNRESOLVED_ATTEMPT_STATUSES for attempt in attempts):
                return f"action {action.id} has an unresolved execution attempt"
            if status is not ActionStatusV1.VERIFIED:
                continue
            verifications = unit_of_work.verifications.list_for_action(action.id)
            latest_verification = max(
                verifications,
                key=lambda item: (item.verified_at_ms, item.verification_no, item.id),
                default=None,
            )
            if latest_verification is None:
                return f"action {action.id} has no verification result"
            if latest_verification.status is not VerificationStatus.VERIFIED:
                return f"action {action.id} verification is unresolved"
        return None

    @staticmethod
    def _attempt_statuses(
        unit_of_work: UnitOfWork, actions: tuple[ActionRecord, ...]
    ) -> tuple[ExecutionAttemptStatusV1, ...]:
        return tuple(
            attempt.status
            for action in actions
            for approval in unit_of_work.approval_history.list_for_action(action.id)
            for attempt in active_attempt_tuple(unit_of_work.execution_attempts, approval.id)
        )

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


__all__ = [
    "CompleteWriteRunCommand",
    "CompleteWriteRunHandler",
    "CompleteWriteRunResult",
]
