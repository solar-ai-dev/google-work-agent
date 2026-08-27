"""Lifecycle transitions for legacy READ actions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from json import dumps

from google_work_agent.application.persistence_cas import update_action_record
from google_work_agent.application.read_contracts import (
    FailReadActionCommand,
    ReadActionCommandResponse,
)
from google_work_agent.application.read_persistence import (
    action_result_response,
    audit_event,
    finish_json_receipt,
    handle_existing_fail_receipt,
    require_action,
    require_plan,
)
from google_work_agent.application.use_cases.run.complete_read_only_run import (
    CompleteReadOnlyRunHandler,
)
from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.action.transitions.fail_read_action import transition_fail_read_action
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import UnitOfWork


class FailReadActionHandler:
    """Mark one executing read action as failed and reconcile dependencies."""

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: FailReadActionCommand) -> ReadActionCommandResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing_receipt = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing_receipt is not None:
                resolution = handle_existing_fail_receipt(
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
                        raise RuntimeError("fail receipt recovery produced no response")
                    return resolution.response

            now_ms = self._now_ms()
            if existing_receipt is None:
                unit_of_work.command_receipts.reserve_or_replay(
                    command_id=command.command_id,
                    command_type="FailReadAction",
                    request_hash=command.request_hash,
                    aggregate_type="Action",
                    aggregate_id=command.action_id,
                    created_at_ms=now_ms,
                )

            action = require_action(unit_of_work, command.action_id)
            plan = require_plan(unit_of_work, action.plan_id)
            result = transition_fail_read_action(
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
                raise RuntimeError("validated FailReadAction CAS failed")
            response = action_result_response(command.action_id, result)
            completion = CompleteReadOnlyRunHandler.try_apply_for_parent(
                unit_of_work,
                parent_command_id=command.command_id,
                run_id=plan.run_id,
                plan_id=plan.id,
                now_ms=now_ms,
            )
            partial = any(
                ActionStatusV1(item.status) is ActionStatusV1.FAILED
                for item in unit_of_work.actions.list_for_plan(plan.id)
            )
            response = ReadActionCommandResponse(
                **{
                    **asdict(response),
                    "plan_completed": completion is not None,
                    "run_completed": completion is not None,
                    "partial": partial,
                    "safe_error_code": command.safe_error_code,
                }
            )
            unit_of_work.traces.append(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=command.action_id,
                    event_type="READ_ACTION_FAILED",
                    status=response.action_status,
                    duration_ms=None,
                    payload_json=dumps(
                        {
                            "command_id": command.command_id,
                            "safe_error_code": command.safe_error_code,
                            "retryable": command.retryable,
                            "detail": command.safe_error_detail,
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.append(
                audit_event(
                    run_id=plan.run_id,
                    action_id=command.action_id,
                    event_type=("ACTION_READ_FAILED" if response.applied else "COMMAND_REJECTED"),
                    outcome=response.result_code,
                    metadata={
                        "command_id": command.command_id,
                        "safe_error_code": command.safe_error_code,
                    },
                    created_at_ms=now_ms,
                )
            )
            finish_json_receipt(
                unit_of_work, command.command_id, response, response.action_version, now_ms
            )
            unit_of_work.commit()
            return response


FailReadActionResult = ReadActionCommandResponse

__all__ = ["FailReadActionCommand", "FailReadActionResult", "FailReadActionHandler"]
