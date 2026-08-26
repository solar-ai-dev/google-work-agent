"""Persistence and publication use cases for write plans."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps
from typing import cast

from google_work_agent.application.plan_invariants import validate_plan_structure
from google_work_agent.application.task_duplicates import TASK_CREATE_TOOL, duplicate_authority
from google_work_agent.application.write_persistence import (
    audit_event as _audit_event,
)
from google_work_agent.application.write_persistence import (
    emit_command_rejected_hash_mismatch as _emit_command_rejected_hash_mismatch,
)
from google_work_agent.application.write_persistence import (
    finish_json_receipt as _finish_json_receipt,
)
from google_work_agent.application.write_persistence import (
    require_plan as _require_plan,
)
from google_work_agent.application.write_persistence import (
    require_run as _require_run,
)
from google_work_agent.application.write_persistence import (
    resolve_json_receipt as _resolve_json_receipt,
)
from google_work_agent.application.write_plan_contracts import (
    PublishWritePlanCommand,
    PublishWritePlanResponse,
    SaveWritePlanCommand,
    SaveWritePlanResponse,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatus, EffectType
from google_work_agent.domain.action_risk import canonicalize_action_risk, normalize_action_risk
from google_work_agent.domain.canonical import (
    calculate_canonical_json_hash,
    canonicalize_json_value,
)
from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.evidence.model import Evidence as EvidenceRecord
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanStatus
from google_work_agent.domain.plan.transitions.publish_plan import transition_publish_plan
from google_work_agent.domain.policy import EvidencePolicyInput, validate_evidence_policy
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatus
from google_work_agent.domain.tool_registry import SignedToolRegistry, build_p0_tool_registry
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import (
    UnitOfWork,
)


class SaveWritePlanService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._registry = build_p0_tool_registry()

    def __call__(self, command: SaveWritePlanCommand) -> SaveWritePlanResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return resolve_existing_save_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    plan_id=command.plan_id,
                    run_id=command.run_id,
                    now_ms=self._now_ms(),
                    response_type=SaveWritePlanResponse,
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="SaveWritePlan",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            run = _require_run(unit_of_work, command.run_id)
            if run.version != command.expected_run_version:
                response = SaveWritePlanResponse(
                    applied=False,
                    result_code=ResultCode.VERSION_CONFLICT.value,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=command.plan_id,
                    plan_status=PlanStatus.DRAFT.value,
                    action_ids=tuple(action.action_id for action in command.actions),
                    conflict_detail="expected_version does not match current_version",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run.version, now_ms
                )
                unit_of_work.commit()
                return response
            if run.status is not RunStatus.PLANNING:
                response = SaveWritePlanResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=command.plan_id,
                    plan_status=PlanStatus.DRAFT.value,
                    action_ids=tuple(action.action_id for action in command.actions),
                    conflict_detail="write plan can only be saved while run is PLANNING",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run.version, now_ms
                )
                unit_of_work.commit()
                return response

            validate_write_plan(command, self._registry)
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
                entry = self._registry.require(action.tool_name)
                unit_of_work.actions.insert_write_action(
                    ActionRecord(
                        id=action.action_id,
                        plan_id=command.plan_id,
                        connector_id=action.connector_id,
                        position=action.position,
                        tool_name=action.tool_name,
                        effect_type=entry.effect_type.value,
                        approval_requirement=entry.approval_requirement.value,
                        verification_policy=entry.verification_policy.value,
                        recovery_policy=entry.recovery_policy.value,
                        target_resource_ref_id=action.target_resource_ref_id,
                        status=ActionStatus.PROPOSED.value,
                        arguments_json=canonicalize_json_value(action.arguments),
                        arguments_hash=calculate_canonical_json_hash(action.arguments),
                        expected_json=canonicalize_json_value(action.expected),
                        risk=normalize_action_risk(action.risk),
                        version=0,
                        created_at_ms=now_ms,
                        updated_at_ms=now_ms,
                    )
                )
                authority = (
                    duplicate_authority(action.risk)
                    if action.tool_name == TASK_CREATE_TOOL
                    else None
                )
                if authority is not None:
                    unit_of_work.audits.add(
                        _audit_event(
                            run_id=command.run_id,
                            action_id=action.action_id,
                            event_type="TASK_DUPLICATE_CHECKED",
                            outcome="EVIDENCE_ONLY",
                            metadata={
                                "decision": authority[0],
                                "matched_count": len(authority[1]),
                                "freshness": "EVIDENCE_ONLY",
                            },
                            created_at_ms=now_ms,
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
                        action_id=action.action_id, evidence_id=evidence_id
                    )

            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=command.run_id,
                    action_id=None,
                    event_type="WRITE_PLAN_SAVED",
                    status=PlanStatus.DRAFT.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"command_id": command.command_id, "plan_id": command.plan_id},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=command.run_id,
                    action_id=None,
                    event_type="ACTION_PROPOSED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"command_id": command.command_id, "plan_id": command.plan_id},
                    created_at_ms=now_ms,
                )
            )
            response = SaveWritePlanResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                run_status=run.status.value,
                run_version=run.version,
                plan_id=command.plan_id,
                plan_status=PlanStatus.DRAFT.value,
                action_ids=tuple(action.action_id for action in command.actions),
            )
            _finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
            unit_of_work.commit()
            return response


class PublishWritePlanService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: PublishWritePlanCommand) -> PublishWritePlanResponse:
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
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="PublishWritePlan",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            plan = _require_plan(unit_of_work, command.plan_id)
            run = _require_run(unit_of_work, command.run_id)
            actions = unit_of_work.actions.list_by_plan(command.plan_id)
            if plan.run_id != command.run_id:
                raise LookupError(f"plan {command.plan_id} does not belong to run {command.run_id}")
            if plan.status is not PlanStatus.DRAFT:
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
                unit_of_work.plans.update_if_status(
                    plan.id,
                    expected_status=plan.status,
                    next_status=next_plan_status,
                )
                is None
            ):
                raise RuntimeError("validated PublishPlan Plan CAS failed")
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=command.run_id,
                    action_id=None,
                    event_type="WRITE_PLAN_PUBLISHED",
                    status=PlanStatus.WAITING_APPROVAL.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"command_id": command.command_id, "plan_id": plan.id}, sort_keys=True
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=command.run_id,
                    action_id=None,
                    event_type="COMMAND_APPLIED",
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
                plan_status=PlanStatus.WAITING_APPROVAL.value,
            )
            _finish_json_receipt(
                unit_of_work, command.command_id, response, run.version + 1, now_ms
            )
            unit_of_work.commit()
            return response


def validate_write_plan(command: SaveWritePlanCommand, registry: SignedToolRegistry) -> None:
    validate_plan_structure(
        actions=command.actions, evidence=command.evidence, plan_label="write plan"
    )
    for action in command.actions:
        if not action.connector_id:
            raise ValueError("write action connector_id is required")
        canonicalize_action_risk(action.risk)
        entry = registry.require(action.tool_name)
        if entry.effect_type is EffectType.READ:
            raise ValueError(f"write plan cannot contain read-only tool: {action.tool_name}")
        validate_evidence_policy(
            policy_input=EvidencePolicyInput(
                evidence_count=len(action.evidence_ids),
                requires_existing_resource=entry.effect_type
                in {EffectType.UPDATE, EffectType.DELETE},
                has_user_selected_resource=action.target_resource_ref_id is not None,
                has_explicit_resource_relation=action.target_resource_ref_id is not None,
            )
        )


def resolve_existing_save_receipt(
    *,
    unit_of_work: UnitOfWork,
    receipt: CommandReceiptRecord,
    request_hash: str,
    plan_id: str,
    run_id: str,
    response_type: type[SaveWritePlanResponse],
    now_ms: int,
) -> SaveWritePlanResponse:
    del plan_id
    if receipt.request_hash != request_hash:
        _emit_command_rejected_hash_mismatch(
            unit_of_work=unit_of_work,
            receipt=receipt,
            run_id=run_id,
            action_id=None,
            now_ms=now_ms,
        )
    return cast(
        SaveWritePlanResponse,
        _resolve_json_receipt(
            receipt=receipt, request_hash=request_hash, response_type=response_type
        ),
    )


def resolve_existing_plan_receipt(
    *,
    unit_of_work: UnitOfWork,
    receipt: CommandReceiptRecord,
    request_hash: str,
    plan_id: str,
    run_id: str,
    response_type: type[PublishWritePlanResponse],
    now_ms: int,
) -> PublishWritePlanResponse:
    del plan_id
    if receipt.request_hash != request_hash:
        _emit_command_rejected_hash_mismatch(
            unit_of_work=unit_of_work,
            receipt=receipt,
            run_id=run_id,
            action_id=None,
            now_ms=now_ms,
        )
    return cast(
        PublishWritePlanResponse,
        _resolve_json_receipt(
            receipt=receipt, request_hash=request_hash, response_type=response_type
        ),
    )
