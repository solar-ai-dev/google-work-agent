"""Action-owner-local persistence and idempotency support for READ commands."""

from __future__ import annotations

from dataclasses import dataclass
from json import dumps, loads

from google_work_agent.application.use_cases.action.read_contracts import (
    ClaimReadActionCommand,
    CompleteReadActionCommand,
    FailReadActionCommand,
    FinalizeReadActionCommand,
    PublishReadOnlyPlanCommand,
    PublishReadOnlyPlanResponse,
    ReadActionCommandResponse,
    SaveReadOnlyPlanCommand,
    SaveReadOnlyPlanResponse,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    finish_json_receipt,
    require_action,
    require_plan,
    require_run,
)
from google_work_agent.application.use_cases.plan.persistence_projection import load_plan_record
from google_work_agent.application.use_cases.plan.project_dependencies import (
    project_dependency_ids,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionCommand, ActionStatusV1, EffectType
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.canonical import (
    calculate_canonical_json_hash,
    canonicalize_json_value,
)
from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import CommandResult, ResultCode
from google_work_agent.domain.run.model import Run as RunRecord
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

READ_ACTION_TERMINAL_STATUSES = frozenset(
    {
        ActionStatusV1.VERIFIED,
        ActionStatusV1.FAILED,
    }
)

DEPENDENCY_FAILURE_STATUSES = frozenset(
    {
        ActionStatusV1.FAILED,
        ActionStatusV1.BLOCKED,
        ActionStatusV1.DEPENDENCY_BLOCKED,
        ActionStatusV1.REJECTED,
        ActionStatusV1.EXPIRED,
        ActionStatusV1.MISMATCH,
    }
)


@dataclass(frozen=True, slots=True)
class _PendingReceiptResolution[T]:
    should_return: bool
    response: T | None = None


@dataclass(frozen=True, slots=True)
class _AggregateState:
    plan_completed: bool
    run_completed: bool
    partial: bool


def action_result_response(
    action_id: str,
    result: CommandResult[ActionStatusV1, ActionCommand],
) -> ReadActionCommandResponse:
    return ReadActionCommandResponse(
        applied=bool(result.applied),
        result_code=result.result_code.value,
        action_id=action_id,
        action_status=result.current_status.value,
        action_version=result.current_version,
        next_allowed_commands=tuple(command.value for command in result.next_allowed_commands),
        conflict_detail=result.conflict_detail,
    )


def action_conflict_response(
    *,
    action: ActionRecord,
    result_code: ResultCode,
    conflict_detail: str,
) -> ReadActionCommandResponse:
    return ReadActionCommandResponse(
        applied=False,
        result_code=result_code.value,
        action_id=action.id,
        action_status=action.status,
        action_version=action.version,
        next_allowed_commands=(),
        conflict_detail=conflict_detail,
    )


def _deserialize_save_plan_response(raw: str) -> SaveReadOnlyPlanResponse:
    payload = loads(raw)
    return SaveReadOnlyPlanResponse(
        applied=bool(payload["applied"]),
        result_code=str(payload["result_code"]),
        run_status=str(payload["run_status"]),
        run_version=int(payload["run_version"]),
        plan_id=str(payload["plan_id"]),
        plan_status=str(payload["plan_status"]),
        action_ids=tuple(str(item) for item in payload["action_ids"]),
        conflict_detail=payload["conflict_detail"],
    )


def _deserialize_publish_plan_response(raw: str) -> PublishReadOnlyPlanResponse:
    payload = loads(raw)
    return PublishReadOnlyPlanResponse(
        applied=bool(payload["applied"]),
        result_code=str(payload["result_code"]),
        run_status=str(payload["run_status"]),
        run_version=int(payload["run_version"]),
        plan_id=str(payload["plan_id"]),
        plan_status=str(payload["plan_status"]),
        conflict_detail=payload["conflict_detail"],
    )


def _deserialize_action_response(raw: str) -> ReadActionCommandResponse:
    payload = loads(raw)
    return ReadActionCommandResponse(
        applied=bool(payload["applied"]),
        result_code=str(payload["result_code"]),
        action_id=str(payload["action_id"]),
        action_status=str(payload["action_status"]),
        action_version=int(payload["action_version"]),
        next_allowed_commands=tuple(str(item) for item in payload["next_allowed_commands"]),
        plan_completed=bool(payload["plan_completed"]),
        run_completed=bool(payload["run_completed"]),
        partial=bool(payload["partial"]),
        safe_error_code=payload["safe_error_code"],
        conflict_detail=payload["conflict_detail"],
    )


def handle_existing_save_receipt(
    *,
    unit_of_work: UnitOfWork,
    command: SaveReadOnlyPlanCommand,
    request_hash: str,
    run_id: str,
    receipt: CommandReceiptRecord,
    completed_at_ms: int,
) -> _PendingReceiptResolution[SaveReadOnlyPlanResponse]:
    if receipt.request_hash != request_hash:
        run = require_run(unit_of_work, run_id)
        return _PendingReceiptResolution(
            should_return=True,
            response=SaveReadOnlyPlanResponse(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                run_status=run.status.value,
                run_version=run.version,
                plan_id="",
                plan_status=PlanStatusV1.DRAFT.value,
                action_ids=(),
                conflict_detail="command_id already exists with a different request_hash",
            ),
        )
    if receipt.response_json is not None and receipt.status is not CommandReceiptStatus.RECEIVED:
        return _PendingReceiptResolution(
            should_return=True,
            response=_deserialize_save_plan_response(receipt.response_json),
        )

    run = require_run(unit_of_work, run_id)
    plan = load_plan_record(unit_of_work.plans, command.plan_id)
    if plan is None:
        if run.status is RunStatusV1.PLANNING and run.version == command.expected_run_version:
            return _PendingReceiptResolution(should_return=False)
        response = _recovery_required_save_response(
            run=run,
            command=command,
            conflict_detail="save_read_only_plan receipt recovery is ambiguous",
        )
        finish_json_receipt(
            unit_of_work, command.command_id, response, run.version, completed_at_ms
        )
        unit_of_work.commit()
        return _PendingReceiptResolution(should_return=True, response=response)

    if _saved_plan_matches(unit_of_work=unit_of_work, command=command, plan=plan):
        response = SaveReadOnlyPlanResponse(
            applied=True,
            result_code=ResultCode.TRANSITION_APPLIED.value,
            run_status=run.status.value,
            run_version=run.version,
            plan_id=plan.id,
            plan_status=plan.status.value,
            action_ids=tuple(action.action_id for action in command.actions),
        )
        finish_json_receipt(
            unit_of_work, command.command_id, response, run.version, completed_at_ms
        )
        unit_of_work.commit()
        return _PendingReceiptResolution(should_return=True, response=response)

    response = _recovery_required_save_response(
        run=run,
        command=command,
        conflict_detail="save_read_only_plan detected partial persisted rows",
    )
    finish_json_receipt(unit_of_work, command.command_id, response, run.version, completed_at_ms)
    unit_of_work.commit()
    return _PendingReceiptResolution(should_return=True, response=response)


def handle_existing_publish_receipt(
    *,
    unit_of_work: UnitOfWork,
    command: PublishReadOnlyPlanCommand,
    request_hash: str,
    run_id: str,
    receipt: CommandReceiptRecord,
    completed_at_ms: int,
) -> _PendingReceiptResolution[PublishReadOnlyPlanResponse]:
    if receipt.request_hash != request_hash:
        run = require_run(unit_of_work, run_id)
        return _PendingReceiptResolution(
            should_return=True,
            response=PublishReadOnlyPlanResponse(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                run_status=run.status.value,
                run_version=run.version,
                plan_id="",
                plan_status=PlanStatusV1.DRAFT.value,
                conflict_detail="command_id already exists with a different request_hash",
            ),
        )
    if receipt.response_json is not None and receipt.status is not CommandReceiptStatus.RECEIVED:
        return _PendingReceiptResolution(
            should_return=True,
            response=_deserialize_publish_plan_response(receipt.response_json),
        )

    run = require_run(unit_of_work, run_id)
    plan = require_plan(unit_of_work, command.plan_id)
    if plan.status in {PlanStatusV1.ACTIVE, PlanStatusV1.COMPLETED} and run.status in {
        RunStatusV1.EXECUTING,
        RunStatusV1.COMPLETED,
    }:
        response = PublishReadOnlyPlanResponse(
            applied=True,
            result_code=ResultCode.TRANSITION_APPLIED.value,
            run_status=run.status.value,
            run_version=run.version,
            plan_id=plan.id,
            plan_status=plan.status.value,
        )
        finish_json_receipt(
            unit_of_work, command.command_id, response, run.version, completed_at_ms
        )
        unit_of_work.commit()
        return _PendingReceiptResolution(should_return=True, response=response)
    if (
        plan.status is PlanStatusV1.DRAFT
        and run.status is RunStatusV1.PLANNING
        and run.version == command.expected_run_version
    ):
        return _PendingReceiptResolution(should_return=False)

    response = PublishReadOnlyPlanResponse(
        applied=False,
        result_code=ResultCode.RECOVERY_REQUIRED.value,
        run_status=run.status.value,
        run_version=run.version,
        plan_id=plan.id,
        plan_status=plan.status.value,
        conflict_detail="publish_read_only_plan receipt recovery is ambiguous",
    )
    finish_json_receipt(unit_of_work, command.command_id, response, run.version, completed_at_ms)
    unit_of_work.commit()
    return _PendingReceiptResolution(should_return=True, response=response)


def handle_existing_claim_receipt(
    *,
    unit_of_work: UnitOfWork,
    command_id: str,
    command: ClaimReadActionCommand,
    request_hash: str,
    action_id: str,
    receipt: CommandReceiptRecord,
    completed_at_ms: int,
) -> _PendingReceiptResolution[ReadActionCommandResponse]:
    if receipt.request_hash != request_hash:
        action = require_action(unit_of_work, action_id)
        return _PendingReceiptResolution(
            should_return=True,
            response=ReadActionCommandResponse(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                action_id=action.id,
                action_status=action.status,
                action_version=action.version,
                next_allowed_commands=(),
                conflict_detail="command_id already exists with a different request_hash",
            ),
        )
    if receipt.response_json is not None and receipt.status is not CommandReceiptStatus.RECEIVED:
        return _PendingReceiptResolution(
            should_return=True,
            response=_deserialize_action_response(receipt.response_json),
        )

    action = require_action(unit_of_work, action_id)
    if (
        action.status != ActionStatusV1.PROPOSED.value
        and action.version >= command.expected_version + 1
    ):
        response = ReadActionCommandResponse(
            applied=True,
            result_code=ResultCode.TRANSITION_APPLIED.value,
            action_id=action.id,
            action_status=action.status,
            action_version=action.version,
            next_allowed_commands=(),
        )
        finish_json_receipt(unit_of_work, command_id, response, action.version, completed_at_ms)
        unit_of_work.commit()
        return _PendingReceiptResolution(should_return=True, response=response)
    if (
        action.status == ActionStatusV1.PROPOSED.value
        and action.version == command.expected_version
    ):
        return _PendingReceiptResolution(should_return=False)

    response = ReadActionCommandResponse(
        applied=False,
        result_code=ResultCode.RECOVERY_REQUIRED.value,
        action_id=action.id,
        action_status=action.status,
        action_version=action.version,
        next_allowed_commands=(),
        conflict_detail="claim_read_action receipt recovery is ambiguous",
    )
    finish_json_receipt(unit_of_work, command_id, response, action.version, completed_at_ms)
    unit_of_work.commit()
    return _PendingReceiptResolution(should_return=True, response=response)


def handle_existing_complete_receipt(
    *,
    unit_of_work: UnitOfWork,
    command_id: str,
    command: CompleteReadActionCommand,
    request_hash: str,
    action_id: str,
    receipt: CommandReceiptRecord,
    completed_at_ms: int,
) -> _PendingReceiptResolution[ReadActionCommandResponse]:
    duplicate_or_terminal = _handle_existing_terminal_action_receipt(
        unit_of_work=unit_of_work,
        command_id=command_id,
        request_hash=request_hash,
        action_id=action_id,
        receipt=receipt,
    )
    if duplicate_or_terminal is not None:
        return duplicate_or_terminal

    action = require_action(unit_of_work, action_id)
    plan = require_plan(unit_of_work, action.plan_id)
    if action.status in {ActionStatusV1.EXECUTED.value, ActionStatusV1.VERIFIED.value}:
        if _complete_projection_matches(
            unit_of_work=unit_of_work,
            run_id=plan.run_id,
            connector_id=action.connector_id,
            command=command,
        ):
            response = ReadActionCommandResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                action_id=action.id,
                action_status=action.status,
                action_version=action.version,
                next_allowed_commands=(),
            )
            finish_json_receipt(unit_of_work, command_id, response, action.version, completed_at_ms)
            unit_of_work.commit()
            return _PendingReceiptResolution(should_return=True, response=response)
        return _return_recovery_required_action(
            unit_of_work=unit_of_work,
            command_id=command_id,
            action=action,
            completed_at_ms=completed_at_ms,
            detail="complete_read_action detected partial projection persistence",
        )
    if (
        action.status == ActionStatusV1.EXECUTING.value
        and action.version == command.expected_version
    ):
        if _complete_projection_matches(
            unit_of_work=unit_of_work,
            run_id=plan.run_id,
            connector_id=action.connector_id,
            command=command,
        ):
            return _return_recovery_required_action(
                unit_of_work=unit_of_work,
                command_id=command_id,
                action=action,
                completed_at_ms=completed_at_ms,
                detail="complete_read_action has projected rows without action transition",
            )
        return _PendingReceiptResolution(should_return=False)
    return _return_recovery_required_action(
        unit_of_work=unit_of_work,
        command_id=command_id,
        action=action,
        completed_at_ms=completed_at_ms,
        detail="complete_read_action receipt recovery is ambiguous",
    )


def handle_existing_finalize_receipt(
    *,
    unit_of_work: UnitOfWork,
    command_id: str,
    command: FinalizeReadActionCommand,
    request_hash: str,
    action_id: str,
    receipt: CommandReceiptRecord,
    completed_at_ms: int,
) -> _PendingReceiptResolution[ReadActionCommandResponse]:
    duplicate_or_terminal = _handle_existing_terminal_action_receipt(
        unit_of_work=unit_of_work,
        command_id=command_id,
        request_hash=request_hash,
        action_id=action_id,
        receipt=receipt,
    )
    if (
        duplicate_or_terminal is not None
        and duplicate_or_terminal.response is not None
        and duplicate_or_terminal.response.result_code == ResultCode.DUPLICATE_COMMAND.value
    ):
        return duplicate_or_terminal

    action = require_action(unit_of_work, action_id)
    plan = require_plan(unit_of_work, action.plan_id)
    if action.status == ActionStatusV1.VERIFIED.value:
        aggregate = _inspect_read_plan_state(unit_of_work, plan.id)
        if _plan_and_run_match_reconciled_state(unit_of_work, plan, aggregate):
            response = ReadActionCommandResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                action_id=action.id,
                action_status=action.status,
                action_version=action.version,
                next_allowed_commands=(),
                plan_completed=aggregate.plan_completed,
                run_completed=aggregate.run_completed,
                partial=aggregate.partial,
            )
            finish_json_receipt(unit_of_work, command_id, response, action.version, completed_at_ms)
            unit_of_work.commit()
            return _PendingReceiptResolution(should_return=True, response=response)
        return _return_recovery_required_action(
            unit_of_work=unit_of_work,
            command_id=command_id,
            action=action,
            completed_at_ms=completed_at_ms,
            detail="finalize_read_action parent reconciliation is incomplete",
        )
    if (
        action.status == ActionStatusV1.EXECUTED.value
        and action.version == command.expected_version
    ):
        return _PendingReceiptResolution(should_return=False)
    return _return_recovery_required_action(
        unit_of_work=unit_of_work,
        command_id=command_id,
        action=action,
        completed_at_ms=completed_at_ms,
        detail="finalize_read_action receipt recovery is ambiguous",
    )


def handle_existing_fail_receipt(
    *,
    unit_of_work: UnitOfWork,
    command_id: str,
    command: FailReadActionCommand,
    request_hash: str,
    action_id: str,
    receipt: CommandReceiptRecord,
    completed_at_ms: int,
) -> _PendingReceiptResolution[ReadActionCommandResponse]:
    duplicate_or_terminal = _handle_existing_terminal_action_receipt(
        unit_of_work=unit_of_work,
        command_id=command_id,
        request_hash=request_hash,
        action_id=action_id,
        receipt=receipt,
    )
    if (
        duplicate_or_terminal is not None
        and duplicate_or_terminal.response is not None
        and duplicate_or_terminal.response.result_code == ResultCode.DUPLICATE_COMMAND.value
    ):
        return duplicate_or_terminal

    action = require_action(unit_of_work, action_id)
    plan = require_plan(unit_of_work, action.plan_id)
    if action.status == ActionStatusV1.FAILED.value:
        aggregate = _inspect_read_plan_state(unit_of_work, plan.id)
        if _plan_and_run_match_reconciled_state(unit_of_work, plan, aggregate):
            response = ReadActionCommandResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                action_id=action.id,
                action_status=action.status,
                action_version=action.version,
                next_allowed_commands=(),
                plan_completed=aggregate.plan_completed,
                run_completed=aggregate.run_completed,
                partial=aggregate.partial,
                safe_error_code=command.safe_error_code,
            )
            finish_json_receipt(unit_of_work, command_id, response, action.version, completed_at_ms)
            unit_of_work.commit()
            return _PendingReceiptResolution(should_return=True, response=response)
        return _return_recovery_required_action(
            unit_of_work=unit_of_work,
            command_id=command_id,
            action=action,
            completed_at_ms=completed_at_ms,
            detail="fail_read_action parent reconciliation is incomplete",
        )
    if (
        action.status == ActionStatusV1.EXECUTING.value
        and action.version == command.expected_version
    ):
        return _PendingReceiptResolution(should_return=False)
    return _return_recovery_required_action(
        unit_of_work=unit_of_work,
        command_id=command_id,
        action=action,
        completed_at_ms=completed_at_ms,
        detail="fail_read_action receipt recovery is ambiguous",
    )


def _read_audit_event(
    *,
    run_id: str,
    action_id: str | None,
    event_type: str,
    outcome: str,
    metadata: dict[str, object],
    created_at_ms: int,
) -> AuditEventRecord:
    return AuditEventRecord(
        account_id=None,
        run_id=run_id,
        action_id=action_id,
        actor_type="AGENT",
        actor_id="read_only_service",
        actor_display="ReadOnlyService",
        event_type=event_type,
        outcome=outcome,
        metadata_json=dumps(metadata, sort_keys=True),
        created_at_ms=created_at_ms,
    )


def _handle_existing_terminal_action_receipt(
    *,
    unit_of_work: UnitOfWork,
    command_id: str,
    request_hash: str,
    action_id: str,
    receipt: CommandReceiptRecord,
) -> _PendingReceiptResolution[ReadActionCommandResponse] | None:
    if receipt.request_hash != request_hash:
        action = require_action(unit_of_work, action_id)
        return _PendingReceiptResolution(
            should_return=True,
            response=ReadActionCommandResponse(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                action_id=action.id,
                action_status=action.status,
                action_version=action.version,
                next_allowed_commands=(),
                conflict_detail="command_id already exists with a different request_hash",
            ),
        )
    if receipt.response_json is not None and receipt.status is not CommandReceiptStatus.RECEIVED:
        return _PendingReceiptResolution(
            should_return=True,
            response=_deserialize_action_response(receipt.response_json),
        )
    return None


def _saved_plan_matches(
    *,
    unit_of_work: UnitOfWork,
    command: SaveReadOnlyPlanCommand,
    plan: PlanRecord,
) -> bool:
    if plan.run_id != command.run_id or plan.revision_no != command.revision_no:
        return False
    persisted_actions = unit_of_work.actions.list_for_plan(plan.id)
    bundle = unit_of_work.plans.load_bundle(plan.id)
    if bundle is None:
        return False
    dependencies = project_dependency_ids(bundle)
    if len(persisted_actions) != len(command.actions):
        return False
    action_by_id = {action.id: action for action in persisted_actions}
    for draft in command.actions:
        action = action_by_id.get(draft.action_id)
        if action is None:
            return False
        if (
            action.position != draft.position
            or action.tool_name != draft.tool_name
            or action.effect_type != EffectType.READ.value
            or action.arguments_hash != calculate_canonical_json_hash(draft.arguments)
            or action.arguments_json != canonicalize_json_value(draft.arguments)
            or action.expected_json != canonicalize_json_value(draft.expected)
        ):
            return False
        if dependencies.get(action.id, ()) != tuple(sorted(draft.depends_on_action_ids)):
            return False
        linked_evidence = {item.id for item in unit_of_work.evidence.list_for_action(action.id)}
        if not set(draft.evidence_ids).issubset(linked_evidence):
            return False

    for evidence in command.evidence:
        if not any(
            item.id == evidence.evidence_id
            and item.origin_type is evidence.origin_type
            and item.kind == evidence.kind
            and item.excerpt == evidence.excerpt
            and item.locator_json == evidence.locator_json
            for action in persisted_actions
            for item in unit_of_work.evidence.list_for_action(action.id)
        ):
            return False
    return True


def _recovery_required_save_response(
    *,
    run: RunRecord,
    command: SaveReadOnlyPlanCommand,
    conflict_detail: str,
) -> SaveReadOnlyPlanResponse:
    return SaveReadOnlyPlanResponse(
        applied=False,
        result_code=ResultCode.RECOVERY_REQUIRED.value,
        run_status=run.status.value,
        run_version=run.version,
        plan_id=command.plan_id,
        plan_status=PlanStatusV1.DRAFT.value,
        action_ids=tuple(action.action_id for action in command.actions),
        conflict_detail=conflict_detail,
    )


def _return_recovery_required_action(
    *,
    unit_of_work: UnitOfWork,
    command_id: str,
    action: ActionRecord,
    completed_at_ms: int,
    detail: str,
) -> _PendingReceiptResolution[ReadActionCommandResponse]:
    response = ReadActionCommandResponse(
        applied=False,
        result_code=ResultCode.RECOVERY_REQUIRED.value,
        action_id=action.id,
        action_status=action.status,
        action_version=action.version,
        next_allowed_commands=(),
        conflict_detail=detail,
    )
    finish_json_receipt(unit_of_work, command_id, response, action.version, completed_at_ms)
    unit_of_work.commit()
    return _PendingReceiptResolution(should_return=True, response=response)


def _complete_projection_matches(
    *,
    unit_of_work: UnitOfWork,
    run_id: str,
    connector_id: str,
    command: CompleteReadActionCommand,
) -> bool:
    persisted_refs = unit_of_work.resource_refs.list_for_run_bounded(run_id, limit=1000)
    for resource_ref in command.resource_refs:
        persisted_ref = next(
            (
                item
                for item in persisted_refs
                if item.connector_id == connector_id
                and item.resource_type == resource_ref.resource_type
                and item.resource_id == resource_ref.resource_id
            ),
            None,
        )
        if persisted_ref is None:
            return False
        if (
            persisted_ref.title != resource_ref.title
            or persisted_ref.metadata_json != resource_ref.metadata_json
            or persisted_ref.version_token != resource_ref.version_token
        ):
            return False

    linked_evidence = {
        item.id: item for item in unit_of_work.evidence.list_for_action(command.action_id)
    }
    for evidence in command.evidence:
        persisted_evidence = linked_evidence.get(evidence.id)
        if persisted_evidence is None:
            return False
        if (
            persisted_evidence.origin_type is not evidence.origin_type
            or persisted_evidence.kind != evidence.kind
            or persisted_evidence.excerpt != evidence.excerpt
            or persisted_evidence.locator_json != evidence.locator_json
            or persisted_evidence.resource_ref_id != evidence.resource_ref_id
        ):
            return False
    return True


def _inspect_read_plan_state(unit_of_work: UnitOfWork, plan_id: str) -> _AggregateState:
    bundle = unit_of_work.plans.load_bundle(plan_id)
    if bundle is None:
        raise LookupError(f"plan not found: {plan_id}")
    actions = bundle.actions
    dependencies = project_dependency_ids(bundle)
    action_statuses = {action.id: ActionStatusV1(action.status) for action in actions}
    if any(
        action_statuses[action.id] is ActionStatusV1.PROPOSED
        and dependencies[action.id]
        and any(
            action_statuses[dep] in DEPENDENCY_FAILURE_STATUSES for dep in dependencies[action.id]
        )
        for action in actions
    ):
        return _AggregateState(plan_completed=False, run_completed=False, partial=True)

    statuses = [ActionStatusV1(action.status) for action in actions]
    partial = any(status is not ActionStatusV1.VERIFIED for status in statuses)
    if any(status not in READ_ACTION_TERMINAL_STATUSES for status in statuses):
        return _AggregateState(plan_completed=False, run_completed=False, partial=partial)
    return _AggregateState(plan_completed=True, run_completed=True, partial=partial)


def _plan_and_run_match_reconciled_state(
    unit_of_work: UnitOfWork,
    plan: PlanRecord,
    aggregate: _AggregateState,
) -> bool:
    run = require_run(unit_of_work, plan.run_id)
    expected_plan_status = (
        PlanStatusV1.COMPLETED if aggregate.plan_completed else PlanStatusV1.ACTIVE
    )
    expected_run_status = (
        RunStatusV1.COMPLETED if aggregate.run_completed else RunStatusV1.EXECUTING
    )
    return plan.status is expected_plan_status and run.status is expected_run_status
