"""Save and publish legacy READ plans."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps

from google_work_agent.application.plan_invariants import validate_plan_structure
from google_work_agent.application.read_contracts import (
    PublishReadOnlyPlanCommand,
    PublishReadOnlyPlanResponse,
    SaveReadOnlyPlanCommand,
    SaveReadOnlyPlanResponse,
)
from google_work_agent.application.read_persistence import (
    audit_event,
    finish_json_receipt,
    handle_existing_publish_receipt,
    handle_existing_save_receipt,
    require_plan,
    require_run,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatus, EffectType
from google_work_agent.domain.canonical import (
    calculate_canonical_json_hash,
    canonicalize_json_value,
)
from google_work_agent.domain.evidence.model import Evidence as EvidenceRecord
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanStatus
from google_work_agent.domain.plan.transitions.publish_read_only_plan import (
    transition_publish_read_only_plan,
)
from google_work_agent.domain.policy import validate_evidence_policy
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatus
from google_work_agent.domain.tool_registry import SignedToolRegistry, build_p0_tool_registry
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import (
    UnitOfWork,
)


class SaveReadOnlyPlanService:
    """Save one explicit read-only plan draft."""

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._registry = build_p0_tool_registry()

    def __call__(self, command: SaveReadOnlyPlanCommand) -> SaveReadOnlyPlanResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing_receipt = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing_receipt is not None:
                resolution = handle_existing_save_receipt(
                    unit_of_work=unit_of_work,
                    command=command,
                    request_hash=command.request_hash,
                    run_id=command.run_id,
                    receipt=existing_receipt,
                    completed_at_ms=self._now_ms(),
                )
                if resolution.should_return:
                    if resolution.response is None:
                        raise RuntimeError("save receipt recovery produced no response")
                    return resolution.response

            now_ms = self._now_ms()
            if existing_receipt is None:
                unit_of_work.command_receipts.add_received(
                    command_id=command.command_id,
                    command_type="SaveReadOnlyPlan",
                    request_hash=command.request_hash,
                    aggregate_type="Run",
                    aggregate_id=command.run_id,
                    created_at_ms=now_ms,
                )

            run = require_run(unit_of_work, command.run_id)
            if run.version != command.expected_run_version:
                response = SaveReadOnlyPlanResponse(
                    applied=False,
                    result_code=ResultCode.VERSION_CONFLICT.value,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=command.plan_id,
                    plan_status=PlanStatus.DRAFT.value,
                    action_ids=tuple(action.action_id for action in command.actions),
                    conflict_detail="expected_version does not match current_version",
                )
                finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
                unit_of_work.commit()
                return response
            if run.status is not RunStatus.PLANNING:
                response = SaveReadOnlyPlanResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=command.plan_id,
                    plan_status=PlanStatus.DRAFT.value,
                    action_ids=tuple(action.action_id for action in command.actions),
                    conflict_detail="read-only plan can only be saved while run is PLANNING",
                )
                finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
                unit_of_work.commit()
                return response

            _validate_read_only_plan(command, self._registry)

            plan = PlanRecord(
                id=command.plan_id,
                run_id=command.run_id,
                revision_no=command.revision_no,
                status=PlanStatus.DRAFT,
                summary_text=command.summary_text,
                created_at_ms=now_ms,
            )
            unit_of_work.plans.insert_draft(plan)

            evidence_by_id = {item.evidence_id: item for item in command.evidence}
            for evidence in command.evidence:
                unit_of_work.evidence.insert(
                    EvidenceRecord(
                        id=evidence.evidence_id,
                        run_id=command.run_id,
                        origin_type=evidence.origin_type,
                        resource_ref_id=evidence.resource_ref_id,
                        message_id=evidence.message_id,
                        kind=evidence.kind,
                        excerpt=evidence.excerpt,
                        locator_json=evidence.locator_json,
                        created_at_ms=now_ms,
                    )
                )

            for action in command.actions:
                registry_entry = self._registry.require(action.tool_name)
                unit_of_work.actions.insert_read_action(
                    ActionRecord(
                        id=action.action_id,
                        plan_id=command.plan_id,
                        connector_id=action.connector_id,
                        position=action.position,
                        tool_name=action.tool_name,
                        effect_type=registry_entry.effect_type.value,
                        approval_requirement=registry_entry.approval_requirement.value,
                        verification_policy=registry_entry.verification_policy.value,
                        recovery_policy=registry_entry.recovery_policy.value,
                        target_resource_ref_id=action.target_resource_ref_id,
                        status=ActionStatus.PROPOSED.value,
                        arguments_json=canonicalize_json_value(action.arguments),
                        arguments_hash=calculate_canonical_json_hash(action.arguments),
                        expected_json=canonicalize_json_value(action.expected),
                        risk={},
                        version=0,
                        created_at_ms=now_ms,
                        updated_at_ms=now_ms,
                    )
                )
                for depends_on_action_id in action.depends_on_action_ids:
                    unit_of_work.action_dependencies.add(
                        action_id=action.action_id,
                        depends_on_action_id=depends_on_action_id,
                    )
                for evidence_id in action.evidence_ids:
                    if evidence_id not in evidence_by_id:
                        raise LookupError(f"evidence not found for action link: {evidence_id}")
                    unit_of_work.evidence.link_to_action(
                        action_id=action.action_id,
                        evidence_id=evidence_id,
                    )

            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=command.run_id,
                    action_id=None,
                    event_type="PLAN_SAVED",
                    status=PlanStatus.DRAFT.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {
                            "command_id": command.command_id,
                            "plan_id": command.plan_id,
                            "action_count": len(command.actions),
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                audit_event(
                    run_id=command.run_id,
                    action_id=None,
                    event_type="ACTION_PROPOSED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={
                        "command_id": command.command_id,
                        "plan_id": command.plan_id,
                        "action_ids": [item.action_id for item in command.actions],
                    },
                    created_at_ms=now_ms,
                )
            )

            response = SaveReadOnlyPlanResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                run_status=run.status.value,
                run_version=run.version,
                plan_id=command.plan_id,
                plan_status=PlanStatus.DRAFT.value,
                action_ids=tuple(action.action_id for action in command.actions),
            )
            finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
            unit_of_work.commit()
            return response


class PublishReadOnlyPlanService:
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
            if plan.status is not PlanStatus.DRAFT:
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
                    event_type="PLAN_PUBLISHED",
                    status=PlanStatus.ACTIVE.value,
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
                    event_type="COMMAND_APPLIED",
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
                plan_status=PlanStatus.ACTIVE.value,
            )
            finish_json_receipt(unit_of_work, command.command_id, response, run.version + 1, now_ms)
            unit_of_work.commit()
            return response


def _validate_read_only_plan(
    command: SaveReadOnlyPlanCommand, registry: SignedToolRegistry
) -> None:
    validate_plan_structure(
        actions=command.actions, evidence=command.evidence, plan_label="read-only plan"
    )
    for action in command.actions:
        if not action.connector_id:
            raise ValueError("read action connector_id is required")
        entry = registry.get(action.tool_name)
        if entry is None:
            raise LookupError(f"tool not registered: {action.tool_name}")
        if entry.effect_type is not EffectType.READ:
            raise ValueError(f"read-only plan cannot include non-read action: {action.tool_name}")
        if entry.approval_requirement.value != "NONE":
            raise ValueError(
                f"read-only plan requires approval_requirement=NONE: {action.tool_name}"
            )
        if entry.verification_policy.value != "NONE":
            raise ValueError(
                f"read-only plan requires verification_policy=NONE: {action.tool_name}"
            )
        if entry.recovery_policy.value != "NONE":
            raise ValueError(f"read-only plan requires recovery_policy=NONE: {action.tool_name}")
        validate_evidence_policy(
            type(
                "EvidencePolicyInput",
                (),
                {
                    "evidence_count": len(action.evidence_ids),
                    "requires_existing_resource": False,
                    "has_user_selected_resource": False,
                    "has_explicit_resource_relation": False,
                },
            )()
        )


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
