"""Lifecycle transitions for legacy READ actions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from json import dumps

from google_work_agent.application.read_contracts import (
    FinalizeReadActionCommand,
    ReadActionCommandResponse,
)
from google_work_agent.application.read_persistence import (
    action_result_response,
    audit_event,
    finish_json_receipt,
    handle_existing_finalize_receipt,
    require_action,
    require_plan,
)
from google_work_agent.application.use_cases.run.complete_read_only_run import (
    CompleteReadOnlyRunHandler,
)
from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.action.transitions.finalize_read_action import (
    transition_finalize_read_action,
)
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import UnitOfWork


class FinalizeReadActionHandler:
    """Finalize one executed read action and reconcile parent state."""

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: FinalizeReadActionCommand) -> ReadActionCommandResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing_receipt = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing_receipt is not None:
                resolution = handle_existing_finalize_receipt(
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
                        raise RuntimeError("finalize receipt recovery produced no response")
                    return resolution.response

            now_ms = self._now_ms()
            if existing_receipt is None:
                unit_of_work.command_receipts.add_received(
                    command_id=command.command_id,
                    command_type="FinalizeReadAction",
                    request_hash=command.request_hash,
                    aggregate_type="Action",
                    aggregate_id=command.action_id,
                    created_at_ms=now_ms,
                )

            action = require_action(unit_of_work, command.action_id)
            plan = require_plan(unit_of_work, action.plan_id)
            result = transition_finalize_read_action(
                ActionStatusV1(action.status),
                action.version,
                command.expected_version,
                effect_type=EffectType(action.effect_type),
            )
            if (
                result.applied
                and unit_of_work.actions.update_if_version_and_status(
                    command.action_id,
                    expected_version=action.version,
                    expected_status=ActionStatusV1(action.status),
                    next_status=result.current_status,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError("validated FinalizeReadAction CAS failed")
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
                for item in unit_of_work.actions.list_by_plan(plan.id)
            )
            response = ReadActionCommandResponse(
                **{
                    **asdict(response),
                    "plan_completed": completion is not None,
                    "run_completed": completion is not None,
                    "partial": partial,
                }
            )
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=command.action_id,
                    event_type="READ_ACTION_FINALIZED",
                    status=response.action_status,
                    duration_ms=None,
                    payload_json=dumps(
                        {"command_id": command.command_id, "partial": partial},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                audit_event(
                    run_id=plan.run_id,
                    action_id=command.action_id,
                    event_type=("ACTION_READ_VERIFIED" if response.applied else "COMMAND_REJECTED"),
                    outcome=response.result_code,
                    metadata={"command_id": command.command_id, "partial": partial},
                    created_at_ms=now_ms,
                )
            )
            finish_json_receipt(
                unit_of_work, command.command_id, response, response.action_version, now_ms
            )
            unit_of_work.commit()
            return response


FinalizeReadActionResult = ReadActionCommandResponse

__all__ = ["FinalizeReadActionCommand", "FinalizeReadActionResult", "FinalizeReadActionHandler"]
