"""Commit the durable dispatch authority before any connector Write."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from json import dumps, loads

from google_work_agent.application.use_cases.action.persistence_cas import (
    update_execution_attempt_record,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    audit_event,
    require_action,
    require_approval,
    require_attempt,
    require_plan,
    require_run,
)
from google_work_agent.application.use_cases.run.cancel_intent import has_durable_cancel_intent
from google_work_agent.domain.action.model import Action, ActionStatusV1
from google_work_agent.domain.approval.model import Approval, ApprovalStatusV1
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttempt,
    ExecutionAttemptStatusV1,
)
from google_work_agent.domain.execution_attempt.transitions.begin_execution_attempt import (
    transition_begin_execution_attempt,
)
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class BeginExecutionAttemptCommand:
    command_id: str
    request_hash: str
    action_id: str
    claim_payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class BeginExecutionAttemptResult:
    action: Action
    approval: Approval
    attempt: ExecutionAttempt


class BeginExecutionAttemptHandler:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: BeginExecutionAttemptCommand) -> BeginExecutionAttemptResult:
        with self._unit_of_work_factory() as unit_of_work:
            result = self.apply_in_unit_of_work(unit_of_work, command, now_ms=self._now_ms())
            unit_of_work.commit()
            return result

    @staticmethod
    def apply_in_unit_of_work(
        unit_of_work: UnitOfWork,
        command: BeginExecutionAttemptCommand,
        *,
        now_ms: int,
    ) -> BeginExecutionAttemptResult:
        payload = command.claim_payload
        if calculate_canonical_json_hash(payload) != command.request_hash:
            raise PermissionError("BeginExecutionAttempt request_hash mismatch")

        # Receipt adjudication precedes mutable-state guards (04-A SS10.0): a
        # replay of an already-APPLIED command_id/hash must keep returning the
        # stored result even if Run/Plan/Action/Approval state advanced since
        # the first success. Only a genuinely new command_id proceeds to the
        # guards below.
        existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
        if existing is not None:
            if existing.request_hash != command.request_hash:
                raise PermissionError("BeginExecutionAttempt command_id hash conflict")
            if (
                existing.status is not CommandReceiptStatus.APPLIED
                or existing.response_json is None
            ):
                raise RuntimeError("BeginExecutionAttempt receipt requires recovery")
            try:
                stored = loads(existing.response_json)
            except (TypeError, ValueError) as error:
                raise RuntimeError("BeginExecutionAttempt receipt requires recovery") from error
            if (
                not isinstance(stored, Mapping)
                or stored.get("applied") is not True
                or stored.get("attempt_id") != str(payload["execution_attempt_id"])
                or stored.get("attempt_status") != ExecutionAttemptStatusV1.EXECUTING.value
                or not isinstance(stored.get("attempt_version"), int)
            ):
                raise RuntimeError("BeginExecutionAttempt receipt requires recovery")
            action = require_action(unit_of_work, command.action_id)
            approval = require_approval(unit_of_work, str(payload["approval_id"]))
            attempt = require_attempt(unit_of_work, str(payload["execution_attempt_id"]))
            action_version = stored.get("action_version", approval.action_version + 1)
            action_updated_at_ms = stored.get("action_updated_at_ms", attempt.started_at_ms)
            approval_consumed_at_ms = stored.get(
                "approval_consumed_at_ms", attempt.started_at_ms
            )
            if (
                not isinstance(action_version, int)
                or not isinstance(action_updated_at_ms, int)
                or not isinstance(approval_consumed_at_ms, int)
            ):
                raise RuntimeError("BeginExecutionAttempt receipt requires recovery")
            replayed_action = replace(
                action,
                status=ActionStatusV1.EXECUTING.value,
                version=action_version,
                updated_at_ms=action_updated_at_ms,
            )
            replayed_approval = replace(
                approval,
                status=ApprovalStatusV1.CONSUMED,
                consumed_at_ms=approval_consumed_at_ms,
            )
            replayed_attempt = replace(
                attempt,
                status=ExecutionAttemptStatusV1.EXECUTING,
                version=int(stored["attempt_version"]),
                result_resource_ref_id=None,
                response_metadata_json=None,
                error_code=None,
                error_detail_json=None,
                finished_at_ms=None,
            )
            return BeginExecutionAttemptResult(
                replayed_action,
                replayed_approval,
                replayed_attempt,
            )

        action = require_action(unit_of_work, command.action_id)
        plan = require_plan(unit_of_work, action.plan_id)
        run = require_run(unit_of_work, plan.run_id)
        approval = require_approval(unit_of_work, str(payload["approval_id"]))
        attempt = require_attempt(unit_of_work, str(payload["execution_attempt_id"]))

        plans = current_plan_tuple(unit_of_work.plans, run.id)
        if not plans:
            raise PermissionError("claim owner Run has no published Plan")
        current_plan = max(plans, key=lambda candidate: candidate.revision_no)
        cancel_intent = has_durable_cancel_intent(unit_of_work.cancel_intents, run.id)
        if cancel_intent or run.status is RunStatusV1.CANCEL_REQUESTED:
            raise PermissionError("cancellation forbids connector Write dispatch")
        if (
            run.status not in {RunStatusV1.WAITING_APPROVAL, RunStatusV1.VERIFYING}
            or plan.status is not PlanStatusV1.WAITING_APPROVAL
            or current_plan.id != plan.id
        ):
            raise PermissionError("claim parent authority is no longer current")
        if action.id != str(payload["action_id"]) or action.tool_name != str(payload["tool_name"]):
            raise PermissionError("claim token action/tool binding mismatch")
        if action.arguments_hash != str(payload["approval_arguments_hash"]):
            raise PermissionError("claim token arguments binding mismatch")
        if approval.action_id != action.id or attempt.approval_id != approval.id:
            raise PermissionError("claim token persistence binding mismatch")

        decision = transition_begin_execution_attempt(
            attempt.status,
            attempt.version,
            attempt.version,
            claim_context_current=(
                action.status == ActionStatusV1.EXECUTING.value
                and approval.status is ApprovalStatusV1.CONSUMED
            ),
            durable_cancel_intent=False,
        )
        if not decision.applied:
            raise PermissionError(decision.conflict_detail or "execution attempt is not claimable")

        unit_of_work.command_receipts.reserve_or_replay(
            command_id=command.command_id,
            command_type="BeginExecutionAttempt",
            request_hash=command.request_hash,
            aggregate_type="ExecutionAttempt",
            aggregate_id=attempt.id,
            created_at_ms=now_ms,
        )
        updated_attempt = update_execution_attempt_record(
            unit_of_work,
            attempt.id,
            expected_version=attempt.version,
            expected_status=attempt.status,
            status=decision.current_status,
            error_code=None,
            error_detail_json=None,
            result_resource_ref_id=None,
            response_metadata_json=None,
            finished_at_ms=None,
        )
        if updated_attempt is None:
            raise RuntimeError("validated BeginExecutionAttempt CAS failed")
        unit_of_work.audits.append(
            audit_event(
                run_id=run.id,
                action_id=action.id,
                event_type="EXECUTION_DISPATCH_STARTED",
                outcome=ResultCode.TRANSITION_APPLIED.value,
                metadata={"attempt_id": updated_attempt.id},
                created_at_ms=now_ms,
            )
        )
        unit_of_work.command_receipts.store_result(
            command_id=command.command_id,
            applied=True,
            result_code=ResultCode.TRANSITION_APPLIED,
            result_version=updated_attempt.version,
            response_json=dumps(
                {
                    "applied": True,
                    "attempt_id": updated_attempt.id,
                    "attempt_status": updated_attempt.status.value,
                    "attempt_version": updated_attempt.version,
                    "action_status": action.status,
                    "action_version": action.version,
                    "action_updated_at_ms": action.updated_at_ms,
                    "approval_status": approval.status.value,
                    "approval_consumed_at_ms": approval.consumed_at_ms,
                },
                sort_keys=True,
            ),
            completed_at_ms=now_ms,
        )
        return BeginExecutionAttemptResult(action, approval, updated_attempt)
