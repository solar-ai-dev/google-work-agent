"""Lifecycle transitions for legacy READ actions."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps

from google_work_agent.application.use_cases.action.persistence_cas import update_action_record
from google_work_agent.application.use_cases.action.read_contracts import (
    ClaimReadActionCommand,
    ReadActionCommandResponse,
)
from google_work_agent.application.use_cases.action.read_persistence import (
    READ_ACTION_TERMINAL_STATUSES,
    action_conflict_response,
    action_result_response,
    audit_event,
    finish_json_receipt,
    handle_existing_claim_receipt,
    require_action,
    require_plan,
    require_run,
)
from google_work_agent.application.use_cases.plan.persistence_projection import current_plan_tuple
from google_work_agent.application.use_cases.run.cancel_intent import has_durable_cancel_intent
from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.action.transitions.claim_read_action import (
    transition_claim_read_action,
)
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


class ClaimReadActionHandler:
    """Claim one read action without invoking the external gateway in-transaction."""

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: ClaimReadActionCommand) -> ReadActionCommandResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing_receipt = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing_receipt is not None:
                resolution = handle_existing_claim_receipt(
                    unit_of_work=unit_of_work,
                    command_id=command.command_id,
                    command=command,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                    receipt=existing_receipt,
                    completed_at_ms=self._now_ms(),
                )
                if resolution.should_return:
                    if resolution.response is None:
                        raise RuntimeError("claim receipt recovery produced no response")
                    return resolution.response

            now_ms = self._now_ms()
            if existing_receipt is None:
                unit_of_work.command_receipts.reserve_or_replay(
                    command_id=command.command_id,
                    command_type="ClaimReadAction",
                    request_hash=command.request_hash,
                    aggregate_type="Action",
                    aggregate_id=command.action_id,
                    created_at_ms=now_ms,
                )

            action = require_action(unit_of_work, command.action_id)
            if ActionStatusV1(action.status) in READ_ACTION_TERMINAL_STATUSES:
                response = action_conflict_response(
                    action=action,
                    result_code=ResultCode.STATE_CONFLICT,
                    conflict_detail="terminal action cannot be claimed again",
                )
                finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response
            if not unit_of_work.actions.is_dependency_ready(action.id):
                response = action_conflict_response(
                    action=action,
                    result_code=ResultCode.STATE_CONFLICT,
                    conflict_detail="dependencies are not yet satisfied",
                )
                finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response

            plan = require_plan(unit_of_work, action.plan_id)
            run = require_run(unit_of_work, plan.run_id)
            plans = current_plan_tuple(unit_of_work.plans, run.id)
            current_plan = max(plans, key=lambda candidate: candidate.revision_no, default=None)
            if (
                plan.status is not PlanStatusV1.ACTIVE
                or run.status is not RunStatusV1.EXECUTING
                or current_plan is None
                or current_plan.id != plan.id
                or has_durable_cancel_intent(unit_of_work.command_receipts, run.id)
            ):
                response = action_conflict_response(
                    action=action,
                    result_code=ResultCode.STATE_CONFLICT,
                    conflict_detail=(
                        "claim requires the current owning Plan/Run and no durable cancel intent"
                    ),
                )
                finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response

            result = transition_claim_read_action(
                ActionStatusV1(action.status),
                action.version,
                command.expected_version,
                effect_type=EffectType(action.effect_type),
            )
            if (
                result.applied
                and update_action_record(
                    unit_of_work,
                    command.action_id,
                    expected_version=action.version,
                    expected_status=ActionStatusV1(action.status),
                    next_status=result.current_status,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError("validated ClaimReadAction CAS failed")
            response = action_result_response(command.action_id, result)
            unit_of_work.traces.append(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=command.action_id,
                    event_type="READ_ACTION_CLAIMED",
                    status=response.action_status,
                    duration_ms=None,
                    payload_json=dumps({"command_id": command.command_id}, sort_keys=True),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.append(
                audit_event(
                    run_id=plan.run_id,
                    action_id=command.action_id,
                    event_type=("ACTION_READ_CLAIMED" if response.applied else "COMMAND_REJECTED"),
                    outcome=response.result_code,
                    metadata={"command_id": command.command_id},
                    created_at_ms=now_ms,
                )
            )
            finish_json_receipt(
                unit_of_work, command.command_id, response, response.action_version, now_ms
            )
            unit_of_work.commit()
            return response


ClaimReadActionResult = ReadActionCommandResponse

__all__ = ["ClaimReadActionCommand", "ClaimReadActionResult", "ClaimReadActionHandler"]
