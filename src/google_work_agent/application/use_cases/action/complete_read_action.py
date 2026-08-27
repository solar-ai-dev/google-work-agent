"""Lifecycle transitions for legacy READ actions."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps

from google_work_agent.application.read_contracts import (
    CompleteReadActionCommand,
    ReadActionCommandResponse,
)
from google_work_agent.application.read_persistence import (
    action_conflict_response,
    action_result_response,
    audit_event,
    finish_json_receipt,
    handle_existing_complete_receipt,
    require_action,
    require_plan,
)
from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.action.transitions.complete_read_action import (
    transition_complete_read_action,
)
from google_work_agent.domain.evidence.model import Evidence as EvidenceRecord
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import UnitOfWork


class CompleteReadActionHandler:
    """Persist the successful result of one read action."""

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: CompleteReadActionCommand) -> ReadActionCommandResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing_receipt = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing_receipt is not None:
                resolution = handle_existing_complete_receipt(
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
                        raise RuntimeError("complete receipt recovery produced no response")
                    return resolution.response

            now_ms = self._now_ms()
            if existing_receipt is None:
                unit_of_work.command_receipts.add_received(
                    command_id=command.command_id,
                    command_type="CompleteReadAction",
                    request_hash=command.request_hash,
                    aggregate_type="Action",
                    aggregate_id=command.action_id,
                    created_at_ms=now_ms,
                )

            action = require_action(unit_of_work, command.action_id)
            plan = require_plan(unit_of_work, action.plan_id)
            if len(command.resource_refs) == 0 and len(command.evidence) == 0:
                raise ValueError(
                    "read completion requires at least one projected resource or evidence"
                )
            if action.version != command.expected_version:
                response = action_conflict_response(
                    action=action,
                    result_code=ResultCode.VERSION_CONFLICT,
                    conflict_detail="expected_version does not match current_version",
                )
                finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response
            if ActionStatusV1(action.status) is not ActionStatusV1.EXECUTING:
                response = action_conflict_response(
                    action=action,
                    result_code=ResultCode.STATE_CONFLICT,
                    conflict_detail="complete_read_action requires EXECUTING status",
                )
                finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response

            if not action.connector_id:
                raise ValueError("persisted READ action connector_id is required")
            for resource_ref in command.resource_refs:
                unit_of_work.resource_refs.upsert_bound_ref(
                    ResourceRefRecord(
                        id=resource_ref.id,
                        run_id=plan.run_id,
                        connector_id=action.connector_id,
                        source=resource_ref.source,
                        resource_type=resource_ref.resource_type,
                        resource_id=resource_ref.resource_id,
                        parent_resource_id=resource_ref.parent_resource_id,
                        canonical_url=resource_ref.canonical_url,
                        title=resource_ref.title,
                        event_time_ms=resource_ref.event_time_ms,
                        version_token=resource_ref.version_token,
                        metadata_json=resource_ref.metadata_json,
                        captured_at_ms=now_ms,
                    )
                )

            for evidence in command.evidence:
                unit_of_work.evidence.insert(
                    EvidenceRecord(
                        id=evidence.id,
                        run_id=plan.run_id,
                        origin_type=evidence.origin_type,
                        resource_ref_id=evidence.resource_ref_id,
                        message_id=evidence.message_id,
                        kind=evidence.kind,
                        excerpt=evidence.excerpt,
                        locator_json=evidence.locator_json,
                        created_at_ms=now_ms,
                    )
                )
                unit_of_work.evidence.link_to_action(
                    action_id=command.action_id, evidence_id=evidence.id
                )

            result = transition_complete_read_action(
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
                raise RuntimeError("validated CompleteReadAction CAS failed")
            response = action_result_response(command.action_id, result)
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=command.action_id,
                    event_type="READ_ACTION_COMPLETED",
                    status=response.action_status,
                    duration_ms=None,
                    payload_json=dumps(
                        {
                            "command_id": command.command_id,
                            "resource_ref_count": len(command.resource_refs),
                            "evidence_count": len(command.evidence),
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                audit_event(
                    run_id=plan.run_id,
                    action_id=command.action_id,
                    event_type=("ACTION_READ_EXECUTED" if response.applied else "COMMAND_REJECTED"),
                    outcome=response.result_code,
                    metadata={
                        "command_id": command.command_id,
                        "resource_ref_count": len(command.resource_refs),
                        "evidence_count": len(command.evidence),
                    },
                    created_at_ms=now_ms,
                )
            )
            finish_json_receipt(
                unit_of_work, command.command_id, response, response.action_version, now_ms
            )
            unit_of_work.commit()
            return response


CompleteReadActionResult = ReadActionCommandResponse

__all__ = ["CompleteReadActionCommand", "CompleteReadActionResult", "CompleteReadActionHandler"]
