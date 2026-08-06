"""WRITE plan approval, claim, execution, and verification flow."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Callable
from dataclasses import asdict, dataclass
from hashlib import sha256
from hmac import compare_digest
from hmac import new as hmac_new
from json import dumps, loads
from typing import cast

from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    ApprovalIntegrityInput,
    ApprovalStatus,
    CommandResult,
    EffectType,
    EvidencePolicyInput,
    ExecutionAttemptStatus,
    PolicyViolationError,
    ResultCode,
    RunStatus,
    SignedToolRegistry,
    VerificationStatus,
    build_p0_tool_registry,
    calculate_canonical_json_hash,
    canonicalize_json_value,
    validate_approval_integrity,
    validate_evidence_policy,
)
from google_work_agent.ports import (
    ActionRecord,
    ApprovalRecord,
    AuditEventRecord,
    CommandReceiptRecord,
    CommandReceiptStatus,
    EvidenceOriginType,
    EvidenceRecord,
    ExecutionAttemptRecord,
    GoogleWorkspaceGateway,
    PlanRecord,
    PlanStatus,
    ResourceRefRecord,
    ResourceSnapshot,
    ResourceSource,
    ResourceType,
    RunRecord,
    StoredResourceType,
    TraceEventRecord,
    UnitOfWork,
    VerificationRecord,
)

CLAIM_TOKEN_VERSION = "v1"
VERIFICATION_NORMALIZER_VERSION = "2026-08-06.p0"
DEFAULT_APPROVAL_TTL_MS = 30_000


@dataclass(frozen=True, slots=True)
class WriteEvidenceDraft:
    evidence_id: str
    origin_type: EvidenceOriginType
    kind: str
    excerpt: str
    locator_json: str | None = None
    resource_ref_id: str | None = None
    message_id: str | None = None


@dataclass(frozen=True, slots=True)
class WriteActionDraft:
    action_id: str
    position: int
    tool_name: str
    arguments: dict[str, object]
    expected: dict[str, object]
    evidence_ids: tuple[str, ...]
    target_resource_ref_id: str | None = None


@dataclass(frozen=True, slots=True)
class SaveWritePlanCommand:
    command_id: str
    request_hash: str
    plan_id: str
    run_id: str
    revision_no: int
    summary_text: str
    expected_run_version: int
    actions: tuple[WriteActionDraft, ...]
    evidence: tuple[WriteEvidenceDraft, ...]


@dataclass(frozen=True, slots=True)
class PublishWritePlanCommand:
    command_id: str
    request_hash: str
    plan_id: str
    run_id: str
    expected_run_version: int


@dataclass(frozen=True, slots=True)
class ApproveWriteActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    approved_by_account_id: str
    approved_by_display: str | None
    source_snapshot: dict[str, object]
    approval_id: str
    idempotency_key: str
    ttl_ms: int = DEFAULT_APPROVAL_TTL_MS


@dataclass(frozen=True, slots=True)
class ClaimWriteActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    source_snapshot: dict[str, object]
    attempt_id: str
    nonce: str


@dataclass(frozen=True, slots=True)
class CompletedWriteAction:
    resource_ref_id: str
    response_metadata_json: str
    snapshot_projection_json: str


@dataclass(frozen=True, slots=True)
class StoreWriteActionSuccessCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    snapshot: ResourceSnapshot


@dataclass(frozen=True, slots=True)
class MarkWriteActionFailedCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    error_code: str
    error_detail: str


@dataclass(frozen=True, slots=True)
class VerifyWriteActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    verification_id: str


@dataclass(frozen=True, slots=True)
class SaveWritePlanResponse:
    applied: bool
    result_code: str
    run_status: str
    run_version: int
    plan_id: str
    plan_status: str
    action_ids: tuple[str, ...]
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class PublishWritePlanResponse:
    applied: bool
    result_code: str
    run_status: str
    run_version: int
    plan_id: str
    plan_status: str
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class WriteActionResponse:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    approval_id: str | None = None
    attempt_id: str | None = None
    claim_token: str | None = None
    safe_error_code: str | None = None
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutedWriteActionResult:
    snapshot: ResourceSnapshot
    response_metadata_json: str


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
                return _resolve_existing_save_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    plan_id=command.plan_id,
                    run_id=command.run_id,
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
                    unit_of_work,
                    command.command_id,
                    response,
                    run.version,
                    now_ms,
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
                    unit_of_work,
                    command.command_id,
                    response,
                    run.version,
                    now_ms,
                )
                unit_of_work.commit()
                return response

            _validate_write_plan(command, self._registry)
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
                        version=0,
                        created_at_ms=now_ms,
                        updated_at_ms=now_ms,
                    )
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
                return _resolve_existing_plan_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    plan_id=command.plan_id,
                    run_id=command.run_id,
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
                    unit_of_work,
                    command.command_id,
                    response,
                    run.version,
                    now_ms,
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
                    unit_of_work,
                    command.command_id,
                    response,
                    run.version,
                    now_ms,
                )
                unit_of_work.commit()
                return response

            run_result = unit_of_work.runs.publish_write_plan(
                command.run_id,
                expected_version=command.expected_run_version,
            )
            if not run_result.applied:
                response = PublishWritePlanResponse(
                    applied=False,
                    result_code=run_result.result_code.value,
                    run_status=run_result.current_status.value,
                    run_version=run_result.current_version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail=run_result.conflict_detail,
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run_result.current_version, now_ms
                )
                unit_of_work.commit()
                return response

            unit_of_work.plans.wait_for_approval(plan.id)
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=command.run_id,
                    action_id=None,
                    event_type="WRITE_PLAN_PUBLISHED",
                    status=PlanStatus.WAITING_APPROVAL.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"command_id": command.command_id, "plan_id": plan.id},
                        sort_keys=True,
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
                run_status=run_result.current_status.value,
                run_version=run_result.current_version,
                plan_id=plan.id,
                plan_status=PlanStatus.WAITING_APPROVAL.value,
            )
            _finish_json_receipt(
                unit_of_work, command.command_id, response, run_result.current_version, now_ms
            )
            unit_of_work.commit()
            return response


class ApproveWriteActionService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._registry = build_p0_tool_registry()

    def __call__(self, command: ApproveWriteActionCommand) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _resolve_existing_action_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="ApproveWriteAction",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            entry = self._registry.require(action.tool_name)
            approval_result = unit_of_work.actions.approve_write(
                action.id,
                expected_version=command.expected_version,
                updated_at_ms=now_ms,
            )
            if not approval_result.applied:
                response = _action_response_from_result(
                    action_id=action.id,
                    result=approval_result,
                )
                _finish_json_receipt(
                    unit_of_work,
                    command.command_id,
                    response,
                    action.version,
                    now_ms,
                )
                unit_of_work.commit()
                return response

            approval = ApprovalRecord(
                id=command.approval_id,
                action_id=action.id,
                approval_no=len(unit_of_work.approvals.list_by_action(action.id)) + 1,
                action_version=approval_result.current_version,
                status=ApprovalStatus.ACTIVE,
                approved_by_account_id=command.approved_by_account_id,
                approved_by_display=command.approved_by_display,
                arguments_snapshot_json=action.arguments_json,
                canonical_arguments_hash=action.arguments_hash,
                source_snapshot_json=canonicalize_json_value(command.source_snapshot),
                source_snapshot_hash=calculate_canonical_json_hash(command.source_snapshot),
                policy_version=entry.policy_version,
                tool_schema_version=entry.schema_version,
                idempotency_key=command.idempotency_key,
                recovery_fingerprint=calculate_recovery_fingerprint(
                    tool_name=action.tool_name,
                    arguments_hash=action.arguments_hash,
                    source_snapshot_hash=calculate_canonical_json_hash(command.source_snapshot),
                ),
                approved_at_ms=now_ms,
                expires_at_ms=now_ms + min(command.ttl_ms, 60_000),
                consumed_at_ms=None,
            )
            unit_of_work.approvals.insert(approval)

            plan = _require_plan(unit_of_work, action.plan_id)
            if plan.status is PlanStatus.WAITING_APPROVAL:
                unit_of_work.plans.activate_waiting(plan.id)

            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_APPROVED",
                    status=ActionStatus.APPROVED.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"approval_id": approval.id, "command_id": command.command_id},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_APPROVED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"approval_id": approval.id, "command_id": command.command_id},
                    created_at_ms=now_ms,
                )
            )
            response = WriteActionResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                action_id=action.id,
                action_status=approval_result.current_status.value,
                action_version=approval_result.current_version,
                next_allowed_commands=tuple(
                    item.value for item in approval_result.next_allowed_commands
                ),
                approval_id=approval.id,
            )
            _finish_json_receipt(
                unit_of_work,
                command.command_id,
                response,
                approval_result.current_version,
                now_ms,
            )
            unit_of_work.commit()
            return response


class ClaimWriteActionService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        signing_secret: str,
        service_instance_id: str,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._signing_secret = signing_secret
        self._service_instance_id = service_instance_id
        self._registry = build_p0_tool_registry()

    def __call__(self, command: ClaimWriteActionCommand) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _resolve_existing_action_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="ClaimWriteAction",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            approval = unit_of_work.approvals.get_active_by_action(action.id)
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
                    unit_of_work,
                    command.command_id,
                    response,
                    action.version,
                    now_ms,
                )
                unit_of_work.commit()
                return response

            entry = self._registry.require(action.tool_name)
            try:
                validate_approval_integrity(
                    ApprovalIntegrityInput(
                        approval_arguments_hash=approval.canonical_arguments_hash,
                        current_arguments_hash=action.arguments_hash,
                        approval_source_snapshot_hash=approval.source_snapshot_hash,
                        current_source_snapshot_hash=calculate_canonical_json_hash(
                            command.source_snapshot
                        ),
                        approval_action_version=approval.action_version,
                        current_action_version=action.version,
                        approval_policy_version=approval.policy_version,
                        current_policy_version=entry.policy_version,
                        approval_tool_schema_version=approval.tool_schema_version,
                        current_tool_schema_version=entry.schema_version,
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
                    unit_of_work,
                    command.command_id,
                    response,
                    action.version,
                    now_ms,
                )
                unit_of_work.commit()
                return response
            if unit_of_work.execution_attempts.get_active_by_approval(approval.id) is not None:
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
                    unit_of_work,
                    command.command_id,
                    response,
                    action.version,
                    now_ms,
                )
                unit_of_work.commit()
                return response

            result = unit_of_work.actions.claim_execution(
                action.id,
                expected_version=command.expected_version,
                updated_at_ms=now_ms,
            )
            if not result.applied:
                response = _action_response_from_result(action_id=action.id, result=result)
                _finish_json_receipt(
                    unit_of_work,
                    command.command_id,
                    response,
                    action.version,
                    now_ms,
                )
                unit_of_work.commit()
                return response

            attempt = ExecutionAttemptRecord(
                id=command.attempt_id,
                approval_id=approval.id,
                attempt_no=len(unit_of_work.execution_attempts.list_by_approval(approval.id)) + 1,
                status=ExecutionAttemptStatus.CLAIMED,
                version=0,
                result_resource_ref_id=None,
                response_metadata_json=None,
                error_code=None,
                error_detail_json=None,
                started_at_ms=now_ms,
                finished_at_ms=None,
            )
            unit_of_work.execution_attempts.insert_claimed(attempt)
            unit_of_work.approvals.mark_consumed(approval.id, consumed_at_ms=now_ms)
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
                    "expires_at_ms": now_ms + DEFAULT_APPROVAL_TTL_MS,
                },
                signing_secret=self._signing_secret,
            )
            plan = _require_plan(unit_of_work, action.plan_id)
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_CLAIMED",
                    status=ActionStatus.EXECUTING.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"approval_id": approval.id, "attempt_id": attempt.id},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
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
                unit_of_work,
                command.command_id,
                response,
                result.current_version,
                now_ms,
            )
            unit_of_work.commit()
            return response


class ExecuteWriteActionService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        gateway: GoogleWorkspaceGateway,
        now_ms: Callable[[], int],
        signing_secret: str,
        service_instance_id: str,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._gateway = gateway
        self._now_ms = now_ms
        self._signing_secret = signing_secret
        self._service_instance_id = service_instance_id
        self._used_nonces: set[str] = set()

    def __call__(self, *, action_id: str, claim_token: str) -> ExecutedWriteActionResult:
        payload = read_claim_token(claim_token, signing_secret=self._signing_secret)
        if str(payload["service_instance_id"]) != self._service_instance_id:
            raise PermissionError("claim token service binding mismatch")
        if self._now_ms() >= _coerce_int(payload["expires_at_ms"]):
            raise PermissionError("claim token has expired")
        nonce = str(payload["nonce"])
        if nonce in self._used_nonces:
            raise PermissionError("claim token has already been used")

        with self._unit_of_work_factory() as unit_of_work:
            action = _require_action(unit_of_work, action_id)
            approval = _require_approval(unit_of_work, str(payload["approval_id"]))
            attempt = _require_attempt(unit_of_work, str(payload["attempt_id"]))
            if action.id != str(payload["action_id"]):
                raise PermissionError("claim token action binding mismatch")
            if action.tool_name != str(payload["tool_name"]):
                raise PermissionError("claim token tool binding mismatch")
            if action.arguments_hash != str(payload["arguments_hash"]):
                raise PermissionError("claim token arguments binding mismatch")
            if approval.action_id != action.id or attempt.approval_id != approval.id:
                raise PermissionError("claim token persistence binding mismatch")
            if attempt.status is not ExecutionAttemptStatus.CLAIMED:
                raise PermissionError("execution attempt is not claimable")

        self._used_nonces.add(nonce)
        snapshot = _dispatch_write_action(
            self._gateway,
            action.tool_name,
            loads(action.arguments_json),
        )
        return ExecutedWriteActionResult(
            snapshot=snapshot,
            response_metadata_json=dumps(
                {"operation": action.tool_name, "resource_id": snapshot.resource_id},
                sort_keys=True,
            ),
        )


class StoreWriteActionSuccessService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: StoreWriteActionSuccessCommand) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _resolve_existing_action_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="StoreWriteActionSuccess",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            plan = _require_plan(unit_of_work, action.plan_id)

            resource_ref = _resource_ref_from_snapshot(
                run_id=plan.run_id,
                snapshot=command.snapshot,
                captured_at_ms=now_ms,
            )
            unit_of_work.resource_refs.upsert(resource_ref)
            unit_of_work.execution_attempts.mark_succeeded(
                attempt.id,
                expected_version=command.expected_attempt_version,
                result_resource_ref_id=resource_ref.id,
                response_metadata_json=dumps(
                    {"operation": action.tool_name, "resource_id": command.snapshot.resource_id},
                    sort_keys=True,
                ),
                finished_at_ms=now_ms,
            )
            result = unit_of_work.actions.store_success(
                action.id,
                expected_version=command.expected_action_version,
                updated_at_ms=now_ms,
            )
            if not result.applied:
                raise RuntimeError(
                    "write action store_success transition failed after attempt success"
                )

            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_EXECUTED",
                    status=ActionStatus.EXECUTED.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"attempt_id": attempt.id, "resource_ref_id": resource_ref.id},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_EXECUTED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"attempt_id": attempt.id, "resource_ref_id": resource_ref.id},
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
                attempt_id=attempt.id,
            )
            _finish_json_receipt(
                unit_of_work,
                command.command_id,
                response,
                result.current_version,
                now_ms,
            )
            unit_of_work.commit()
            return response


class MarkWriteActionFailedService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: MarkWriteActionFailedCommand) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _resolve_existing_action_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="MarkWriteActionFailed",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            unit_of_work.execution_attempts.mark_failed(
                attempt.id,
                expected_version=command.expected_attempt_version,
                error_code=command.error_code,
                error_detail_json=dumps({"detail": command.error_detail}, sort_keys=True),
                finished_at_ms=now_ms,
            )
            result = unit_of_work.actions.mark_failed(
                action.id,
                expected_version=command.expected_action_version,
                updated_at_ms=now_ms,
            )
            if not result.applied:
                raise RuntimeError(
                    "write action mark_failed transition failed after attempt failure"
                )

            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_FAILED",
                    status=ActionStatus.FAILED.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"attempt_id": attempt.id, "error_code": command.error_code},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_FAILED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"attempt_id": attempt.id, "error_code": command.error_code},
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
                attempt_id=attempt.id,
                safe_error_code=command.error_code,
            )
            _finish_json_receipt(
                unit_of_work,
                command.command_id,
                response,
                result.current_version,
                now_ms,
            )
            unit_of_work.commit()
            return response


class VerifyWriteActionService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        gateway: GoogleWorkspaceGateway,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._gateway = gateway

    def __call__(self, command: VerifyWriteActionCommand) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _resolve_existing_action_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="VerifyWriteAction",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            if attempt.status is not ExecutionAttemptStatus.SUCCEEDED:
                response = WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=action.id,
                    action_status=action.status,
                    action_version=action.version,
                    next_allowed_commands=(),
                    attempt_id=attempt.id,
                    conflict_detail="verification requires a succeeded execution attempt",
                )
                _finish_json_receipt(
                    unit_of_work,
                    command.command_id,
                    response,
                    action.version,
                    now_ms,
                )
                unit_of_work.commit()
                return response

            actual_snapshot = _load_verification_snapshot(
                gateway=self._gateway,
                action=action,
                result_resource_ref_id=attempt.result_resource_ref_id,
                unit_of_work=unit_of_work,
            )
            expected = loads(action.expected_json)
            actual_projection = normalize_verification_projection(actual_snapshot)
            diff = calculate_verification_diff(expected, actual_projection)
            verification_status = (
                VerificationStatus.VERIFIED if len(diff) == 0 else VerificationStatus.MISMATCH
            )
            verification = VerificationRecord(
                id=command.verification_id,
                execution_attempt_id=attempt.id,
                verification_no=len(unit_of_work.verifications.list_by_attempt(attempt.id)) + 1,
                status=verification_status,
                normalizer_version=VERIFICATION_NORMALIZER_VERSION,
                expected_json=canonicalize_json_value(expected),
                actual_json=canonicalize_json_value(actual_projection),
                diff_json=canonicalize_json_value(diff),
                verified_at_ms=now_ms,
            )
            unit_of_work.verifications.insert(verification)
            result = unit_of_work.actions.store_verification(
                action.id,
                expected_version=command.expected_action_version,
                updated_at_ms=now_ms,
                verification_status=verification_status.value,
            )
            if not result.applied:
                raise RuntimeError("write action store_verification transition failed")

            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_VERIFIED",
                    status=verification_status.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"attempt_id": attempt.id, "verification_id": verification.id},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_VERIFIED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={
                        "attempt_id": attempt.id,
                        "verification_id": verification.id,
                        "verification_status": verification_status.value,
                    },
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
                attempt_id=attempt.id,
            )
            _finish_json_receipt(
                unit_of_work,
                command.command_id,
                response,
                result.current_version,
                now_ms,
            )
            unit_of_work.commit()
            return response


def normalize_claim_token_payload(payload: dict[str, object]) -> bytes:
    return canonicalize_json_value(payload).encode("utf-8")


def calculate_claim_token_signature(payload_bytes: bytes, *, signing_secret: str) -> str:
    return hmac_new(signing_secret.encode("utf-8"), payload_bytes, sha256).hexdigest()


def issue_claim_token(payload: dict[str, object], *, signing_secret: str) -> str:
    payload_bytes = normalize_claim_token_payload(payload)
    encoded_payload = urlsafe_b64encode(payload_bytes).decode("ascii")
    signature = calculate_claim_token_signature(payload_bytes, signing_secret=signing_secret)
    return f"{encoded_payload}.{signature}"


def read_claim_token(token: str, *, signing_secret: str) -> dict[str, object]:
    encoded_payload, signature = token.split(".", 1)
    payload_bytes = urlsafe_b64decode(encoded_payload.encode("ascii"))
    expected_signature = calculate_claim_token_signature(
        payload_bytes, signing_secret=signing_secret
    )
    if not compare_digest(signature, expected_signature):
        raise PermissionError("claim token signature mismatch")
    payload = loads(payload_bytes.decode("utf-8"))
    if str(payload.get("version")) != CLAIM_TOKEN_VERSION:
        raise PermissionError("claim token version mismatch")
    return cast(dict[str, object], payload)


def calculate_recovery_fingerprint(
    *, tool_name: str, arguments_hash: str, source_snapshot_hash: str
) -> str:
    return calculate_canonical_json_hash(
        {
            "tool_name": tool_name,
            "arguments_hash": arguments_hash,
            "source_snapshot_hash": source_snapshot_hash,
        }
    )


def normalize_verification_projection(snapshot: ResourceSnapshot) -> dict[str, object]:
    return {
        "resource_type": snapshot.resource_type.value,
        "resource_id": snapshot.resource_id,
        "parent_id": snapshot.parent_id,
        "version": snapshot.version,
        "payload": snapshot.payload,
    }


def calculate_verification_diff(
    expected: object,
    actual: object,
    *,
    path: str = "$",
) -> list[dict[str, object]]:
    if type(expected) is not type(actual):
        return [{"path": path, "expected": expected, "actual": actual}]
    if isinstance(expected, dict) and isinstance(actual, dict):
        expected_map = cast(dict[str, object], expected)
        actual_map = cast(dict[str, object], actual)
        diffs: list[dict[str, object]] = []
        expected_keys = set(expected_map)
        actual_keys = set(actual_map)
        for key in sorted(expected_keys | actual_keys):
            if key not in expected_map or key not in actual_map:
                diffs.append(
                    {
                        "path": f"{path}.{key}",
                        "expected": expected_map.get(key, "<missing>"),
                        "actual": actual_map.get(key, "<missing>"),
                    }
                )
                continue
            diffs.extend(
                calculate_verification_diff(
                    expected_map[key],
                    actual_map[key],
                    path=f"{path}.{key}",
                )
            )
        return diffs
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [{"path": path, "expected": expected, "actual": actual}]
        list_diffs: list[dict[str, object]] = []
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual, strict=False)):
            list_diffs.extend(
                calculate_verification_diff(expected_item, actual_item, path=f"{path}[{index}]")
            )
        return list_diffs
    if expected != actual:
        return [{"path": path, "expected": expected, "actual": actual}]
    return []


def _validate_write_plan(
    command: SaveWritePlanCommand,
    registry: SignedToolRegistry,
) -> None:
    if len(command.actions) == 0:
        raise ValueError("write plan requires at least one action")
    evidence_count = len(command.evidence)
    for action in command.actions:
        entry = registry.require(action.tool_name)
        if entry.effect_type is EffectType.READ:
            raise ValueError(f"write plan cannot contain read-only tool: {action.tool_name}")
        validate_evidence_policy(
            policy_input=EvidencePolicyInput(
                evidence_count=evidence_count,
                requires_existing_resource=entry.effect_type is EffectType.UPDATE,
                has_user_selected_resource=action.target_resource_ref_id is not None,
                has_explicit_resource_relation=action.target_resource_ref_id is not None,
            )
        )


def _dispatch_write_action(
    gateway: GoogleWorkspaceGateway,
    tool_name: str,
    arguments: dict[str, object],
) -> ResourceSnapshot:
    payload = _dict_argument(arguments.get("payload"))
    if tool_name == "gmail_create_draft":
        return gateway.create_gmail_draft(payload=payload)
    if tool_name == "gmail_update_draft":
        return gateway.update_gmail_draft(draft_id=str(arguments["draft_id"]), payload=payload)
    if tool_name == "tasks_create_task":
        return gateway.create_task(task_list_id=str(arguments["task_list_id"]), payload=payload)
    if tool_name == "tasks_update_task":
        return gateway.update_task(
            task_list_id=str(arguments["task_list_id"]),
            task_id=str(arguments["task_id"]),
            payload=payload,
        )
    if tool_name == "calendar_create_event":
        return gateway.create_calendar_event(
            calendar_id=str(arguments["calendar_id"]),
            payload=payload,
        )
    if tool_name == "calendar_update_event":
        return gateway.update_calendar_event(
            calendar_id=str(arguments["calendar_id"]),
            event_id=str(arguments["event_id"]),
            payload=payload,
        )
    raise LookupError(f"unsupported write tool: {tool_name}")


def _load_verification_snapshot(
    *,
    gateway: GoogleWorkspaceGateway,
    action: ActionRecord,
    result_resource_ref_id: str | None,
    unit_of_work: UnitOfWork,
) -> ResourceSnapshot:
    arguments = loads(action.arguments_json)
    if action.tool_name in {"gmail_create_draft", "gmail_update_draft"}:
        draft_id = str(
            arguments.get("draft_id") or _resource_id_from_ref(unit_of_work, result_resource_ref_id)
        )
        return gateway.get_gmail_draft(draft_id=draft_id)
    if action.tool_name in {"tasks_create_task", "tasks_update_task"}:
        task_list_id = str(arguments["task_list_id"])
        task_id = str(
            arguments.get("task_id") or _resource_id_from_ref(unit_of_work, result_resource_ref_id)
        )
        return gateway.get_task(task_list_id=task_list_id, task_id=task_id)
    if action.tool_name in {"calendar_create_event", "calendar_update_event"}:
        calendar_id = str(arguments["calendar_id"])
        event_id = str(
            arguments.get("event_id") or _resource_id_from_ref(unit_of_work, result_resource_ref_id)
        )
        return gateway.get_calendar_event(calendar_id=calendar_id, event_id=event_id)
    raise LookupError(f"unsupported verification tool: {action.tool_name}")


def _resource_id_from_ref(unit_of_work: UnitOfWork, resource_ref_id: str | None) -> str:
    if resource_ref_id is None:
        raise LookupError("result_resource_ref_id is required for verification")
    resource_ref = unit_of_work.resource_refs.get_by_id(resource_ref_id)
    if resource_ref is None:
        raise LookupError(f"resource ref not found: {resource_ref_id}")
    return resource_ref.resource_id


def _resource_ref_from_snapshot(
    *, run_id: str, snapshot: ResourceSnapshot, captured_at_ms: int
) -> ResourceRefRecord:
    source_map = {
        ResourceType.GMAIL_DRAFT: (ResourceSource.GMAIL, StoredResourceType.MESSAGE),
        ResourceType.TASK: (ResourceSource.TASKS, StoredResourceType.TASK),
        ResourceType.CALENDAR_EVENT: (ResourceSource.CALENDAR, StoredResourceType.EVENT),
    }
    source, stored_resource_type = source_map[snapshot.resource_type]
    title = str(
        snapshot.payload.get("subject") or snapshot.payload.get("title") or snapshot.resource_id
    )
    return ResourceRefRecord(
        id=f"resource-ref-{run_id}-{snapshot.resource_type.value}-{snapshot.resource_id}",
        run_id=run_id,
        source=source,
        resource_type=stored_resource_type,
        resource_id=snapshot.resource_id,
        parent_resource_id=snapshot.parent_id,
        canonical_url=None,
        title=title[:200],
        event_time_ms=None,
        version_token=snapshot.version,
        metadata_json=dumps(snapshot.payload, sort_keys=True),
        captured_at_ms=captured_at_ms,
    )


def _action_response_from_result(
    *,
    action_id: str,
    result: CommandResult[ActionStatus, ActionCommand],
) -> WriteActionResponse:
    return WriteActionResponse(
        applied=result.applied,
        result_code=result.result_code.value,
        action_id=action_id,
        action_status=result.current_status.value,
        action_version=result.current_version,
        next_allowed_commands=tuple(item.value for item in result.next_allowed_commands),
        conflict_detail=result.conflict_detail,
    )


def _resolve_existing_save_receipt(
    *,
    unit_of_work: UnitOfWork,
    receipt: CommandReceiptRecord,
    request_hash: str,
    plan_id: str,
    run_id: str,
    response_type: type[SaveWritePlanResponse],
) -> SaveWritePlanResponse:
    del unit_of_work, plan_id, run_id
    return cast(
        SaveWritePlanResponse,
        _resolve_json_receipt(
            receipt=receipt,
            request_hash=request_hash,
            response_type=response_type,
        ),
    )


def _resolve_existing_plan_receipt(
    *,
    unit_of_work: UnitOfWork,
    receipt: CommandReceiptRecord,
    request_hash: str,
    plan_id: str,
    run_id: str,
    response_type: type[PublishWritePlanResponse],
) -> PublishWritePlanResponse:
    del unit_of_work, plan_id, run_id
    return cast(
        PublishWritePlanResponse,
        _resolve_json_receipt(
            receipt=receipt,
            request_hash=request_hash,
            response_type=response_type,
        ),
    )


def _resolve_existing_action_receipt(
    *,
    unit_of_work: UnitOfWork,
    receipt: CommandReceiptRecord,
    request_hash: str,
    action_id: str,
) -> WriteActionResponse:
    del unit_of_work, action_id
    return cast(
        WriteActionResponse,
        _resolve_json_receipt(
            receipt=receipt,
            request_hash=request_hash,
            response_type=WriteActionResponse,
        ),
    )


def _resolve_json_receipt(
    *,
    receipt: CommandReceiptRecord,
    request_hash: str,
    response_type: type[SaveWritePlanResponse]
    | type[PublishWritePlanResponse]
    | type[WriteActionResponse],
) -> SaveWritePlanResponse | PublishWritePlanResponse | WriteActionResponse:
    if receipt.request_hash != request_hash:
        if response_type is WriteActionResponse:
            return WriteActionResponse(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                action_id=receipt.aggregate_id or "",
                action_status="UNKNOWN",
                action_version=receipt.result_version or 0,
                next_allowed_commands=(),
                conflict_detail="command_id already exists with a different request_hash",
            )
        if response_type is SaveWritePlanResponse:
            return SaveWritePlanResponse(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                run_status="UNKNOWN",
                run_version=receipt.result_version or 0,
                plan_id=receipt.aggregate_id or "",
                plan_status="UNKNOWN",
                action_ids=(),
                conflict_detail="command_id already exists with a different request_hash",
            )
        return PublishWritePlanResponse(
            applied=False,
            result_code=ResultCode.DUPLICATE_COMMAND.value,
            run_status="UNKNOWN",
            run_version=receipt.result_version or 0,
            plan_id=receipt.aggregate_id or "",
            plan_status="UNKNOWN",
            conflict_detail="command_id already exists with a different request_hash",
        )
    if receipt.response_json is None or receipt.status is CommandReceiptStatus.RECEIVED:
        raise RuntimeError("RECEIVED receipt recovery is not implemented for write flow")
    payload = loads(receipt.response_json)
    if "next_allowed_commands" in payload:
        payload["next_allowed_commands"] = tuple(payload["next_allowed_commands"])
    if "action_ids" in payload:
        payload["action_ids"] = tuple(payload["action_ids"])
    return response_type(**payload)


def _finish_json_receipt(
    unit_of_work: UnitOfWork,
    command_id: str,
    response: SaveWritePlanResponse | PublishWritePlanResponse | WriteActionResponse,
    result_version: int,
    completed_at_ms: int,
) -> None:
    unit_of_work.command_receipts.finish_json(
        command_id=command_id,
        applied=bool(response.applied),
        result_code=ResultCode(str(response.result_code)),
        result_version=result_version,
        response_json=dumps(asdict(response), sort_keys=True),
        completed_at_ms=completed_at_ms,
    )


def _require_run(unit_of_work: UnitOfWork, run_id: str) -> RunRecord:
    run = unit_of_work.runs.get_by_id(run_id)
    if run is None:
        raise LookupError(f"run not found: {run_id}")
    return run


def _require_plan(unit_of_work: UnitOfWork, plan_id: str) -> PlanRecord:
    plan = unit_of_work.plans.get_by_id(plan_id)
    if plan is None:
        raise LookupError(f"plan not found: {plan_id}")
    return plan


def _require_action(unit_of_work: UnitOfWork, action_id: str) -> ActionRecord:
    action = unit_of_work.actions.get_by_id(action_id)
    if action is None:
        raise LookupError(f"action not found: {action_id}")
    return action


def _require_approval(unit_of_work: UnitOfWork, approval_id: str) -> ApprovalRecord:
    approval = unit_of_work.approvals.get_by_id(approval_id)
    if approval is None:
        raise LookupError(f"approval not found: {approval_id}")
    return approval


def _require_attempt(unit_of_work: UnitOfWork, attempt_id: str) -> ExecutionAttemptRecord:
    attempt = unit_of_work.execution_attempts.get_by_id(attempt_id)
    if attempt is None:
        raise LookupError(f"execution attempt not found: {attempt_id}")
    return attempt


def _dict_argument(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("expected a dict payload")
    return {str(key): cast(object, item) for key, item in value.items()}


def _coerce_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise TypeError("expected an int-compatible value")


def _audit_event(
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
        actor_id="write_action_service",
        actor_display="WriteActionService",
        event_type=event_type,
        outcome=outcome,
        metadata_json=dumps(metadata, sort_keys=True),
        created_at_ms=created_at_ms,
    )
