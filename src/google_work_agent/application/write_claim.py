"""Claim validation and durable claim issuance for write actions."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps, loads
from typing import cast

from google_work_agent.application.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
    approval_calendar_conflict_authority,
    calendar_conflict_authority,
    calendar_conflict_change_requires_reapproval,
)
from google_work_agent.application.cancel_intent import has_durable_cancel_intent
from google_work_agent.application.feasibility import (
    approval_feasibility_authority,
    feasibility_authority,
    feasibility_change_requires_reapproval,
)
from google_work_agent.application.persistence_cas import (
    update_action_record,
    update_approval_status,
)
from google_work_agent.application.policy import ApprovalIntegrityInput, validate_approval_integrity
from google_work_agent.application.task_duplicates import (
    TASK_CREATE_TOOL,
    approval_duplicate_authority,
    duplicate_authority,
    duplicate_change_requires_reapproval,
)
from google_work_agent.application.write_action_arguments import dict_argument as _dict_argument
from google_work_agent.application.write_execution_contracts import (
    ClaimWriteActionCommand,
    WriteActionResponse,
)
from google_work_agent.application.write_execution_integrity import (
    CLAIM_TOKEN_VERSION,
    issue_claim_token,
)
from google_work_agent.application.write_persistence import (
    action_response_from_result as _action_response_from_result,
)
from google_work_agent.application.write_persistence import (
    audit_event as _audit_event,
)
from google_work_agent.application.write_persistence import (
    finish_json_receipt as _finish_json_receipt,
)
from google_work_agent.application.write_persistence import (
    require_action as _require_action,
)
from google_work_agent.application.write_persistence import (
    require_plan as _require_plan,
)
from google_work_agent.application.write_persistence import (
    require_run as _require_run,
)
from google_work_agent.application.write_persistence import (
    resolve_existing_action_receipt as _resolve_existing_action_receipt,
)
from google_work_agent.domain.action.model import ActionStatusV1, EffectType, PolicyViolationError
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.claim.transitions.claim_execution import transition_claim_execution
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttempt as ExecutionAttemptRecord,
)
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import (
    AttachmentDescriptor,
    AttachmentDescriptorVerifier,
    AttachmentStagingError,
    UnitOfWork,
)
from google_work_agent.ports.connector.claim_context_contract import (
    CLAIM_CONTEXT_DEFAULT_TTL_MS,
    validate_claim_ttl_ms,
)
from google_work_agent.ports.connector.migration_contracts.tool_registry import (
    build_p0_tool_registry,
)
from google_work_agent.ports.persistence.execution_attempt_repository import active_attempt_tuple
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple


class ClaimWriteActionService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        signing_secret: str,
        service_instance_id: str,
        claim_ttl_ms: int = CLAIM_CONTEXT_DEFAULT_TTL_MS,
        attachment_verifier: AttachmentDescriptorVerifier | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._signing_secret = signing_secret
        self._service_instance_id = service_instance_id
        self._claim_ttl_ms = validate_claim_ttl_ms(claim_ttl_ms)
        self._attachment_verifier = attachment_verifier
        self._registry = build_p0_tool_registry()

    def __call__(self, command: ClaimWriteActionCommand) -> WriteActionResponse:
        attachment_error = self._verify_attachments_before_transaction(command.action_id)
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _resolve_existing_action_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                    now_ms=self._now_ms(),
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="ClaimWriteAction",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            if attachment_error is not None:
                response = WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=action.id,
                    action_status=action.status,
                    action_version=action.version,
                    next_allowed_commands=(),
                    conflict_detail=attachment_error,
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response
            plan = _require_plan(unit_of_work, action.plan_id)
            run = _require_run(unit_of_work, plan.run_id)
            plans = tuple(current_plan_tuple(unit_of_work.plans, run.id))
            current_plan = max(
                plans,
                key=lambda candidate: getattr(candidate, "revision_no", 0),
                default=None,
            )
            if has_durable_cancel_intent(unit_of_work.cancel_intents, run.id):
                response = WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=action.id,
                    action_status=action.status,
                    action_version=action.version,
                    next_allowed_commands=(),
                    conflict_detail="durable cancel intent forbids a new write claim",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response

            if (
                run.status not in {RunStatusV1.WAITING_APPROVAL, RunStatusV1.VERIFYING}
                or plan.status is not PlanStatusV1.WAITING_APPROVAL
                or current_plan is None
                or current_plan.id != plan.id
            ):
                response = WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=action.id,
                    action_status=action.status,
                    action_version=action.version,
                    next_allowed_commands=(),
                    conflict_detail=(
                        "claim requires the current published Plan and legal parent Run"
                    ),
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response
            approval = unit_of_work.approvals.get_active_for_action(action.id)
            if approval is None:
                response = WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=action.id,
                    action_status=action.status,
                    action_version=action.version,
                    next_allowed_commands=(),
                    conflict_detail="write action requires an active approval",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response

            entry = self._registry.require(action.tool_name)
            current_source_snapshot = command.source_snapshot
            if action.tool_name == TASK_CREATE_TOOL:
                stored_approval_snapshot = _dict_argument(loads(approval.source_snapshot_json))
                if duplicate_change_requires_reapproval(
                    approved=approval_duplicate_authority(stored_approval_snapshot),
                    current=duplicate_authority(action.risk),
                ):
                    response = WriteActionResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=(),
                        conflict_detail="task duplicate risk changed after approval",
                    )
                    _finish_json_receipt(
                        unit_of_work, command.command_id, response, action.version, now_ms
                    )
                    unit_of_work.commit()
                    return response
                task_duplicate_snapshot = stored_approval_snapshot.get("task_duplicate")
                current_source_snapshot = {
                    **command.source_snapshot,
                    "task_duplicate": task_duplicate_snapshot,
                }
            if action.tool_name in CALENDAR_CONFLICT_TOOLS:
                stored_approval_snapshot = _dict_argument(loads(approval.source_snapshot_json))
                if feasibility_change_requires_reapproval(
                    approved=approval_feasibility_authority(stored_approval_snapshot),
                    current=feasibility_authority(action.risk),
                ):
                    response = WriteActionResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=(),
                        conflict_detail="feasibility risk changed after approval",
                    )
                    _finish_json_receipt(
                        unit_of_work, command.command_id, response, action.version, now_ms
                    )
                    unit_of_work.commit()
                    return response
                if calendar_conflict_change_requires_reapproval(
                    approved=approval_calendar_conflict_authority(stored_approval_snapshot),
                    current=calendar_conflict_authority(action.risk),
                ):
                    response = WriteActionResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=(),
                        conflict_detail="calendar conflict risk changed after approval",
                    )
                    _finish_json_receipt(
                        unit_of_work, command.command_id, response, action.version, now_ms
                    )
                    unit_of_work.commit()
                    return response
                current_source_snapshot = {
                    **command.source_snapshot,
                    "calendar_conflict": stored_approval_snapshot.get("calendar_conflict"),
                    "feasibility": stored_approval_snapshot.get("feasibility"),
                }
            try:
                validate_approval_integrity(
                    ApprovalIntegrityInput(
                        approval_arguments_hash=approval.canonical_arguments_hash,
                        current_arguments_hash=action.arguments_hash,
                        approval_source_snapshot_hash=approval.source_snapshot_hash,
                        current_source_snapshot_hash=calculate_canonical_json_hash(
                            current_source_snapshot
                        ),
                        approval_action_version=approval.action_version,
                        current_action_version=action.version,
                        approval_policy_version=approval.policy_version,
                        current_policy_version=entry.registry_version,
                        approval_tool_schema_version=approval.tool_schema_version,
                        current_tool_schema_version=entry.input_schema_version,
                        now_ms=now_ms,
                        expires_at_ms=approval.expires_at_ms,
                    )
                )
            except PolicyViolationError as error:
                response = WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=action.id,
                    action_status=action.status,
                    action_version=action.version,
                    next_allowed_commands=(),
                    conflict_detail=str(error),
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response
            if unit_of_work.execution_attempts.get_active_for_approval(approval.id) is not None:
                response = WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=action.id,
                    action_status=action.status,
                    action_version=action.version,
                    next_allowed_commands=(),
                    conflict_detail="write action already has an active execution attempt",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response

            preview = transition_claim_execution(
                ActionStatusV1(action.status),
                action.version,
                command.expected_version,
                effect_type=EffectType(action.effect_type),
            )
            if not preview.applied:
                response = _action_response_from_result(action_id=action.id, result=preview)
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response

            if not update_approval_status(

                unit_of_work,
                approval.id,
                expected_status=approval.status,
                next_status=ApprovalStatusV1.CONSUMED,
                consumed_at_ms=now_ms,
            ):
                raise RuntimeError("validated ConsumeApproval CAS failed")
            if (
                update_action_record(
                    unit_of_work,
                    action.id,
                    expected_version=action.version,
                    expected_status=ActionStatusV1(action.status),
                    next_status=preview.current_status,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError("validated ClaimExecution CAS failed")
            result = preview

            attempt = ExecutionAttemptRecord(
                id=command.attempt_id,
                approval_id=approval.id,
                attempt_no=len(
                    active_attempt_tuple(unit_of_work.execution_attempts, approval.id)
                )
                + 1,
                status=ExecutionAttemptStatusV1.CLAIMED,
                version=0,
                result_resource_ref_id=None,
                response_metadata_json=None,
                error_code=None,
                error_detail_json=None,
                started_at_ms=now_ms,
                finished_at_ms=None,
            )
            unit_of_work.execution_attempts.insert_claimed(attempt)
            claim_token = issue_claim_token(
                {
                    "version": CLAIM_TOKEN_VERSION,
                    "action_id": action.id,
                    "approval_id": approval.id,
                    "attempt_id": attempt.id,
                    "tool_name": action.tool_name,
                    "arguments_hash": action.arguments_hash,
                    "service_instance_id": self._service_instance_id,
                    "nonce": command.nonce,
                    "issued_at_ms": now_ms,
                    "expires_at_ms": now_ms + self._claim_ttl_ms,
                },
                signing_secret=self._signing_secret,
            )
            unit_of_work.traces.append(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_CLAIMED",
                    status=ActionStatusV1.EXECUTING.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"approval_id": approval.id, "attempt_id": attempt.id}, sort_keys=True
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.append(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_CLAIMED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"approval_id": approval.id, "attempt_id": attempt.id},
                    created_at_ms=now_ms,
                )
            )
            response = WriteActionResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                action_id=action.id,
                action_status=result.current_status.value,
                action_version=result.current_version,
                next_allowed_commands=tuple(item.value for item in result.next_allowed_commands),
                approval_id=approval.id,
                attempt_id=attempt.id,
                claim_token=claim_token,
            )
            _finish_json_receipt(
                unit_of_work, command.command_id, response, result.current_version, now_ms
            )
            unit_of_work.commit()
            return response

    def _verify_attachments_before_transaction(self, action_id: str) -> str | None:
        with self._unit_of_work_factory() as unit_of_work:
            action = _require_action(unit_of_work, action_id)
            arguments = loads(action.arguments_json)
        if not isinstance(arguments, dict):
            return "ATTACHMENT_DESCRIPTOR_MALFORMED"
        payload = arguments.get("payload")
        if not isinstance(payload, dict) or "attachments" not in payload:
            return None
        values = payload.get("attachments")
        if not isinstance(values, list) or len(values) > 10:
            return "ATTACHMENT_DESCRIPTOR_MALFORMED"
        if not values:
            return None
        if self._attachment_verifier is None:
            return "ATTACHMENT_VERIFIER_UNAVAILABLE"
        try:
            for value in values:
                if not isinstance(value, dict):
                    raise AttachmentStagingError("ATTACHMENT_DESCRIPTOR_MALFORMED")
                descriptor = AttachmentDescriptor.from_json(cast(dict[str, object], value))
                self._attachment_verifier.verify_descriptor(descriptor)
        except AttachmentStagingError as error:
            return error.safe_code
        return None
