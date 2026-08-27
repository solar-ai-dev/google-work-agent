"""Save and publish legacy READ plans."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps

from google_work_agent.application.read_contracts import (
    PublishReadOnlyPlanCommand,
    PublishReadOnlyPlanResponse,
)
from google_work_agent.application.read_persistence import (
    audit_event,
    finish_json_receipt,
    handle_existing_publish_receipt,
    require_plan,
    require_run,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import EffectType
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.plan.transitions.publish_read_only_plan import (
    transition_publish_read_only_plan,
)
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import (
    UnitOfWork,
)


class PublishReadOnlyPlanHandler:
    """Publish one saved read-only plan."""

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: PublishReadOnlyPlanCommand) -> PublishReadOnlyPlanResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing_receipt = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing_receipt is not None:
                resolution = handle_existing_publish_receipt(
                    unit_of_work=unit_of_work,
                    command=command,
                    request_hash=command.request_hash,
                    run_id=command.run_id,
                    receipt=existing_receipt,
                    completed_at_ms=self._now_ms(),
                )
                if resolution.should_return:
                    if resolution.response is None:
                        raise RuntimeError("publish receipt recovery produced no response")
                    return resolution.response

            now_ms = self._now_ms()
            if existing_receipt is None:
                unit_of_work.command_receipts.add_received(
                    command_id=command.command_id,
                    command_type="PublishReadOnlyPlan",
                    request_hash=command.request_hash,
                    aggregate_type="Run",
                    aggregate_id=command.run_id,
                    created_at_ms=now_ms,
                )

            plan = require_plan(unit_of_work, command.plan_id)
            run = require_run(unit_of_work, command.run_id)
            actions = unit_of_work.actions.list_by_plan(command.plan_id)

            if plan.run_id != command.run_id:
                raise LookupError(f"plan {command.plan_id} does not belong to run {command.run_id}")
            if plan.status is not PlanStatusV1.DRAFT:
                response = PublishReadOnlyPlanResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail="plan must be DRAFT before publish",
                )
                finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
                unit_of_work.commit()
                return response
            if len(actions) == 0:
                response = PublishReadOnlyPlanResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail="read-only plan requires at least one action",
                )
                finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
                unit_of_work.commit()
                return response
            _validate_published_actions_are_read(actions)

            if run.version != command.expected_run_version:
                response = PublishReadOnlyPlanResponse(
                    applied=False,
                    result_code=ResultCode.VERSION_CONFLICT.value,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail="expected_version does not match current_version",
                )
                finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
                unit_of_work.commit()
                return response
            next_run_status, next_plan_status = transition_publish_read_only_plan(
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
                raise RuntimeError("validated PublishReadOnlyPlan Run CAS failed")
            if (
                unit_of_work.plans.update_if_status(
                    plan.id,
                    expected_status=plan.status,
                    next_status=next_plan_status,
                )
                is None
            ):
                raise RuntimeError("validated PublishReadOnlyPlan Plan CAS failed")
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=command.run_id,
                    action_id=None,
                    event_type="READ_PLAN_PUBLISHED",
                    status=PlanStatusV1.ACTIVE.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"command_id": command.command_id, "plan_id": plan.id}, sort_keys=True
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                audit_event(
                    run_id=command.run_id,
                    action_id=None,
                    event_type="READ_PLAN_PUBLISHED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"command_id": command.command_id, "plan_id": plan.id},
                    created_at_ms=now_ms,
                )
            )
            response = PublishReadOnlyPlanResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                run_status=next_run_status.value,
                run_version=run.version + 1,
                plan_id=plan.id,
                plan_status=PlanStatusV1.ACTIVE.value,
            )
            finish_json_receipt(unit_of_work, command.command_id, response, run.version + 1, now_ms)
            unit_of_work.commit()
            return response


def _validate_published_actions_are_read(actions: tuple[ActionRecord, ...]) -> None:
    for action in actions:
        if action.effect_type != EffectType.READ.value:
            raise ValueError("publish_read_only_plan requires only READ actions")
        if action.approval_requirement != "NONE":
            raise ValueError("publish_read_only_plan requires approval_requirement=NONE")
        if action.verification_policy != "NONE":
            raise ValueError("publish_read_only_plan requires verification_policy=NONE")
        if action.recovery_policy != "NONE":
            raise ValueError("publish_read_only_plan requires recovery_policy=NONE")


PublishReadOnlyPlanResult = PublishReadOnlyPlanResponse

__all__ = ["PublishReadOnlyPlanCommand", "PublishReadOnlyPlanResult", "PublishReadOnlyPlanHandler"]
