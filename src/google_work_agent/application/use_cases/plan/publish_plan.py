"""Persistence and publication use cases for write plans."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps
from typing import overload

from google_work_agent.application.use_cases.action.persistence_cas import update_plan_record
from google_work_agent.application.use_cases.action.write_persistence import (
    audit_event as _audit_event,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    finish_json_receipt as _finish_json_receipt,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    require_plan as _require_plan,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    require_run as _require_run,
)
from google_work_agent.application.use_cases.plan._write_plan_persistence import (
    _WritePlanPersistence,
    resolve_existing_plan_receipt,
)
from google_work_agent.application.use_cases.plan.write_plan_contracts import (
    PublishWritePlanCommand,
    PublishWritePlanResponse,
    SaveWritePlanCommand,
    SaveWritePlanResponse,
)
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.plan.transitions.publish_plan import transition_publish_plan
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


class PublishPlanHandler:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._draft_persistence = _WritePlanPersistence(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )

    def save(self, command: SaveWritePlanCommand) -> SaveWritePlanResponse:
        """Persist the draft as a private phase of the canonical publish operation."""

        return self._draft_persistence(command)

    @overload
    def __call__(self, command: SaveWritePlanCommand) -> SaveWritePlanResponse: ...

    @overload
    def __call__(self, command: PublishWritePlanCommand) -> PublishWritePlanResponse: ...

    def __call__(
        self, command: SaveWritePlanCommand | PublishWritePlanCommand
    ) -> SaveWritePlanResponse | PublishWritePlanResponse:
        if isinstance(command, SaveWritePlanCommand):
            return self.save(command)
        return self._publish(command)

    def _publish(self, command: PublishWritePlanCommand) -> PublishWritePlanResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return resolve_existing_plan_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    plan_id=command.plan_id,
                    run_id=command.run_id,
                    now_ms=self._now_ms(),
                    response_type=PublishWritePlanResponse,
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="PublishWritePlan",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            plan = _require_plan(unit_of_work, command.plan_id)
            run = _require_run(unit_of_work, command.run_id)
            actions = unit_of_work.actions.list_for_plan(command.plan_id)
            if plan.run_id != command.run_id:
                raise LookupError(f"plan {command.plan_id} does not belong to run {command.run_id}")
            if plan.status is not PlanStatusV1.DRAFT:
                response = PublishWritePlanResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail="plan must be DRAFT before publish",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run.version, now_ms
                )
                unit_of_work.commit()
                return response
            if len(actions) == 0:
                response = PublishWritePlanResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail="write plan requires at least one action",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run.version, now_ms
                )
                unit_of_work.commit()
                return response

            if run.version != command.expected_run_version:
                response = PublishWritePlanResponse(
                    applied=False,
                    result_code=ResultCode.VERSION_CONFLICT.value,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail="expected_version does not match current_version",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run.version, now_ms
                )
                unit_of_work.commit()
                return response
            next_run_status, next_plan_status = transition_publish_plan(
                run.status,
                plan.status,
                review_status=plan.review_status,
            )
            if not unit_of_work.runs.update_if_version_and_status(
                run.id,
                run.version,
                frozenset({run.status}),
                {"status": next_run_status.value, "version": run.version + 1},
            ):
                raise RuntimeError("validated PublishPlan Run CAS failed")
            if (
                update_plan_record(
                    unit_of_work,
                    plan.id,
                    expected_status=plan.status,
                    next_status=next_plan_status,
                )
                is None
            ):
                raise RuntimeError("validated PublishPlan Plan CAS failed")
            unit_of_work.traces.append(
                TraceEventRecord(
                    run_id=command.run_id,
                    action_id=None,
                    event_type="PLAN_PUBLISHED",
                    status=PlanStatusV1.WAITING_APPROVAL.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"command_id": command.command_id, "plan_id": plan.id}, sort_keys=True
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.append(
                _audit_event(
                    run_id=command.run_id,
                    action_id=None,
                    event_type="PLAN_PUBLISHED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"command_id": command.command_id, "plan_id": plan.id},
                    created_at_ms=now_ms,
                )
            )
            response = PublishWritePlanResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                run_status=next_run_status.value,
                run_version=run.version + 1,
                plan_id=plan.id,
                plan_status=PlanStatusV1.WAITING_APPROVAL.value,
            )
            _finish_json_receipt(
                unit_of_work, command.command_id, response, run.version + 1, now_ms
            )
            unit_of_work.commit()
            return response


PublishPlanCommand = PublishWritePlanCommand
PublishPlanResult = PublishWritePlanResponse

__all__ = ["PublishPlanCommand", "PublishPlanResult", "PublishPlanHandler"]
