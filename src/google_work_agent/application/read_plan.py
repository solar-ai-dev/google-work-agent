"""Save and publish legacy READ plans."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps

from google_work_agent.application.plan_invariants import validate_plan_structure
from google_work_agent.application.policy import validate_evidence_policy
from google_work_agent.application.read_contracts import (
    SaveReadOnlyPlanCommand,
    SaveReadOnlyPlanResponse,
)
from google_work_agent.application.read_persistence import (
    audit_event,
    finish_json_receipt,
    handle_existing_save_receipt,
    require_run,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.tool_registry.signed_tool_registry import (
    SignedToolRegistry,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.canonical import (
    calculate_canonical_json_hash,
    canonicalize_json_value,
)
from google_work_agent.domain.evidence.model import Evidence as EvidenceRecord
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1
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
        self._catalog = load_signed_tool_registry()

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
                unit_of_work.command_receipts.reserve_or_replay(
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
                    plan_status=PlanStatusV1.DRAFT.value,
                    action_ids=tuple(action.action_id for action in command.actions),
                    conflict_detail="expected_version does not match current_version",
                )
                finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
                unit_of_work.commit()
                return response
            if run.status is not RunStatusV1.PLANNING:
                response = SaveReadOnlyPlanResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=command.plan_id,
                    plan_status=PlanStatusV1.DRAFT.value,
                    action_ids=tuple(action.action_id for action in command.actions),
                    conflict_detail="read-only plan can only be saved while run is PLANNING",
                )
                finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
                unit_of_work.commit()
                return response

            _validate_read_only_plan(command, self._catalog)

            plan = PlanRecord(
                id=command.plan_id,
                run_id=command.run_id,
                revision_no=command.revision_no,
                status=PlanStatusV1.DRAFT,
                summary_text=command.summary_text,
                created_at_ms=now_ms,
            )
            unit_of_work.plans.insert_revision(plan)

            evidence_by_id = {item.evidence_id: item for item in command.evidence}
            for evidence in command.evidence:
                unit_of_work.evidence.insert_bounded(
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
                registry_entry = self._catalog.get_required(
                    connector_id=action.connector_id, tool_id=action.tool_name
                )
                unit_of_work.actions.insert_for_plan(
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
                        status=ActionStatusV1.PROPOSED.value,
                        arguments_json=canonicalize_json_value(action.arguments),
                        arguments_hash=calculate_canonical_json_hash(action.arguments),
                        expected_json=canonicalize_json_value(action.expected),
                        risk={},
                        version=0,
                        created_at_ms=now_ms,
                        updated_at_ms=now_ms,
                    ),
                    dependency_ids=action.depends_on_action_ids,
                    evidence_ids=action.evidence_ids,
                )
                for evidence_id in action.evidence_ids:
                    if evidence_id not in evidence_by_id:
                        raise LookupError(f"evidence not found for action link: {evidence_id}")

            unit_of_work.traces.append(
                TraceEventRecord(
                    run_id=command.run_id,
                    action_id=None,
                    event_type="PLAN_SAVED",
                    status=PlanStatusV1.DRAFT.value,
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
            unit_of_work.audits.append(
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
                plan_status=PlanStatusV1.DRAFT.value,
                action_ids=tuple(action.action_id for action in command.actions),
            )
            finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
            unit_of_work.commit()
            return response


def _validate_read_only_plan(command: SaveReadOnlyPlanCommand, catalog: SignedToolRegistry) -> None:
    validate_plan_structure(
        actions=command.actions, evidence=command.evidence, plan_label="read-only plan"
    )
    for action in command.actions:
        if not action.connector_id:
            raise ValueError("read action connector_id is required")
        entry = catalog.get_required(
            connector_id=action.connector_id, tool_id=action.tool_name
        )
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
