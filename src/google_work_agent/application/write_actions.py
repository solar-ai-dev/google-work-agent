"""WRITE plan approval, claim, execution, and verification flow."""

from __future__ import annotations

import threading
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from hashlib import sha256
from hmac import compare_digest
from hmac import new as hmac_new
from json import dumps, loads
from typing import Protocol, cast

from google_work_agent.application.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
    CalendarConflictValidator,
    approval_calendar_conflict_authority,
    approval_source_snapshot_for_calendar_conflict,
    calendar_conflict_authority,
    calendar_conflict_change_requires_reapproval,
    merge_calendar_conflict_risk,
    require_calendar_conflict_acknowledgement,
)
from google_work_agent.application.task_duplicates import (
    TASK_CREATE_TOOL,
    TaskDuplicateValidator,
    approval_duplicate_authority,
    approval_source_snapshot_for_task_duplicate,
    duplicate_authority,
    duplicate_change_requires_reapproval,
    merge_duplicate_risk,
    require_duplicate_acknowledgement,
)
from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    ApprovalIntegrityInput,
    ApprovalStatus,
    CalendarConflictDecision,
    CalendarWorkHours,
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
    canonicalize_action_risk,
    canonicalize_json_value,
    next_allowed_action_commands,
    normalize_action_risk,
    validate_approval_integrity,
    validate_evidence_policy,
)
from google_work_agent.ports import (
    ActionRecord,
    ApprovalRecord,
    AuditEventRecord,
    CommandReceiptRecord,
    CommandReceiptStatus,
    DeliveryCertainty,
    EvidenceOriginType,
    EvidenceRecord,
    ExecutionAttemptRecord,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGateway,
    GoogleWorkspaceGatewayError,
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


class VerificationSnapshotGateway(Protocol):
    """Read capability required by deterministic write verification."""

    def get_gmail_message(self, *, message_id: str) -> ResourceSnapshot: ...

    def get_gmail_draft(self, *, draft_id: str) -> ResourceSnapshot: ...

    def get_task(self, *, task_list_id: str, task_id: str) -> ResourceSnapshot: ...

    def get_calendar_event(self, *, calendar_id: str, event_id: str) -> ResourceSnapshot: ...


CLAIM_TOKEN_VERSION = "v1"
VERIFICATION_NORMALIZER_VERSION = "2026-08-06.p0"
DEFAULT_APPROVAL_TTL_MS = 30_000

# GET_ABSENT delete tools: tool_name -> (resource type, argument holding the
# target resource id, argument holding the parent/container id). The
# calendar and task GET_ABSENT verification and GET_TARGET recovery paths
# both key off this same mapping.
_DELETE_TOOL_TARGETS: dict[str, tuple[ResourceType, str, str]] = {
    "calendar_delete_event": (ResourceType.CALENDAR_EVENT, "event_id", "calendar_id"),
    "tasks_delete_task": (ResourceType.TASK, "task_id", "task_list_id"),
}


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
    depends_on_action_ids: tuple[str, ...] = ()
    target_resource_ref_id: str | None = None
    # Only deterministic Domain/Application validators may populate this field.
    risk: dict[str, object] = field(default_factory=dict)


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
    duplicate_acknowledged: bool = False
    calendar_conflict_acknowledged: bool = False


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
class MarkWriteActionUnknownResultCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    error_code: str
    error_detail: str


@dataclass(frozen=True, slots=True)
class RecoverExistingWriteResultCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    snapshot: ResourceSnapshot
    safe_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class RecoverUnknownCreateActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int


@dataclass(frozen=True, slots=True)
class RecoverUnknownUpdateActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int


@dataclass(frozen=True, slots=True)
class RecoverUnknownSendActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int


@dataclass(frozen=True, slots=True)
class RecoverUnknownDeleteActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int


@dataclass(frozen=True, slots=True)
class ResolveUnknownWriteAsFailedCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    error_code: str
    error_detail: str


@dataclass(frozen=True, slots=True)
class PrepareWriteRetryCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_action_version: int


@dataclass(frozen=True, slots=True)
class RequestRunCancellationCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_run_version: int


@dataclass(frozen=True, slots=True)
class FinalizeRunCancellationCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_run_version: int


class RecoveryResolutionKind(StrEnum):
    ACCEPT_PARTIAL = "ACCEPT_PARTIAL"
    CREATE_CORRECTIVE_PLAN = "CREATE_CORRECTIVE_PLAN"


@dataclass(frozen=True, slots=True)
class ResolveMismatchRecoveryCommand:
    command_id: str
    request_hash: str
    run_id: str
    action_id: str
    expected_run_version: int
    resolution_kind: RecoveryResolutionKind
    corrective_plan_id: str | None = None


@dataclass(frozen=True, slots=True)
class RequireWriteReauthCommand:
    command_id: str
    request_hash: str
    run_id: str
    action_id: str | None
    safe_error_code: str


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
class WriteRunResponse:
    applied: bool
    result_code: str
    run_id: str
    run_status: str
    run_version: int
    plan_id: str | None
    plan_status: str | None
    result_kind: str | None = None
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
            approval_source_snapshot = command.source_snapshot
            duplicate_decision = None
            calendar_decision = None
            if action.tool_name == TASK_CREATE_TOOL and action.version == command.expected_version:
                try:
                    duplicate_decision = require_duplicate_acknowledgement(
                        risk=action.risk,
                        acknowledged=command.duplicate_acknowledged,
                    )
                except PolicyViolationError as error:
                    plan = _require_plan(unit_of_work, action.plan_id)
                    response = WriteActionResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=tuple(
                            item.value
                            for item in next_allowed_action_commands(
                                ActionStatus(action.status),
                                effect_type=EffectType(action.effect_type),
                            )
                        ),
                        conflict_detail=str(error),
                    )
                    unit_of_work.audits.add(
                        _audit_event(
                            run_id=plan.run_id,
                            action_id=action.id,
                            event_type="TASK_DUPLICATE_APPROVAL_BLOCKED",
                            outcome=ResultCode.STATE_CONFLICT.value,
                            metadata={
                                "command_id": command.command_id,
                                "decision": (duplicate_authority(action.risk) or ("UNKNOWN", ()))[
                                    0
                                ],
                            },
                            created_at_ms=now_ms,
                        )
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
                approval_source_snapshot = {
                    **command.source_snapshot,
                    **approval_source_snapshot_for_task_duplicate(
                        risk=action.risk,
                        acknowledged=command.duplicate_acknowledged,
                    ),
                }
            if (
                action.tool_name in CALENDAR_CONFLICT_TOOLS
                and action.version == command.expected_version
            ):
                try:
                    calendar_decision = require_calendar_conflict_acknowledgement(
                        risk=action.risk,
                        acknowledged=command.calendar_conflict_acknowledged,
                    )
                except PolicyViolationError as error:
                    plan = _require_plan(unit_of_work, action.plan_id)
                    response = WriteActionResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=tuple(
                            item.value
                            for item in next_allowed_action_commands(
                                ActionStatus(action.status),
                                effect_type=EffectType(action.effect_type),
                            )
                        ),
                        conflict_detail=str(error),
                    )
                    unit_of_work.audits.add(
                        _audit_event(
                            run_id=plan.run_id,
                            action_id=action.id,
                            event_type="CALENDAR_CONFLICT_APPROVAL_BLOCKED",
                            outcome=ResultCode.STATE_CONFLICT.value,
                            metadata={
                                "command_id": command.command_id,
                                **_calendar_conflict_audit_metadata(
                                    risk=action.risk, action_id=action.id
                                ),
                            },
                            created_at_ms=now_ms,
                        )
                    )
                    _finish_json_receipt(
                        unit_of_work, command.command_id, response, action.version, now_ms
                    )
                    unit_of_work.commit()
                    return response
                approval_source_snapshot = {
                    **approval_source_snapshot,
                    **approval_source_snapshot_for_calendar_conflict(
                        risk=action.risk,
                        acknowledged=command.calendar_conflict_acknowledged,
                    ),
                }
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
                source_snapshot_json=canonicalize_json_value(approval_source_snapshot),
                source_snapshot_hash=calculate_canonical_json_hash(approval_source_snapshot),
                policy_version=entry.registry_version,
                tool_schema_version=entry.input_schema_version,
                idempotency_key=command.idempotency_key,
                recovery_fingerprint=calculate_recovery_fingerprint(
                    tool_name=action.tool_name,
                    arguments_hash=action.arguments_hash,
                    source_snapshot_hash=calculate_canonical_json_hash(approval_source_snapshot),
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
            if (
                action.tool_name == TASK_CREATE_TOOL
                and duplicate_decision is not None
                and duplicate_decision.value != "NOT_DUPLICATE"
            ):
                unit_of_work.audits.add(
                    _audit_event(
                        run_id=plan.run_id,
                        action_id=action.id,
                        event_type="TASK_DUPLICATE_OVERRIDE_ACKNOWLEDGED",
                        outcome=ResultCode.TRANSITION_APPLIED.value,
                        metadata={
                            "approval_id": approval.id,
                            "decision": duplicate_decision.value,
                        },
                        created_at_ms=now_ms,
                    )
                )
            if (
                action.tool_name in CALENDAR_CONFLICT_TOOLS
                and calendar_decision is not None
                and calendar_decision is not CalendarConflictDecision.NO_CONFLICT
            ):
                unit_of_work.audits.add(
                    _audit_event(
                        run_id=plan.run_id,
                        action_id=action.id,
                        event_type="CALENDAR_CONFLICT_OVERRIDE_ACKNOWLEDGED",
                        outcome=ResultCode.TRANSITION_APPLIED.value,
                        metadata={
                            "approval_id": approval.id,
                            **_calendar_conflict_audit_metadata(
                                risk=action.risk, action_id=action.id
                            ),
                        },
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
            plan = _require_plan(unit_of_work, action.plan_id)
            run = _require_run(unit_of_work, plan.run_id)
            if run.status in {
                RunStatus.CANCEL_REQUESTED,
                RunStatus.CANCELLED,
                RunStatus.RECOVERY_REQUIRED,
            }:
                response = WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=action.id,
                    action_status=action.status,
                    action_version=action.version,
                    next_allowed_commands=(),
                    conflict_detail="run status forbids a new write claim",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response
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
                        unit_of_work,
                        command.command_id,
                        response,
                        action.version,
                        now_ms,
                    )
                    unit_of_work.commit()
                    return response
                # Task duplicate authority is server-owned. Claim never
                # accepts a client projection in place of the Approval snapshot.
                task_duplicate_snapshot = stored_approval_snapshot.get("task_duplicate")
                current_source_snapshot = {
                    **command.source_snapshot,
                    "task_duplicate": task_duplicate_snapshot,
                }
            if action.tool_name in CALENDAR_CONFLICT_TOOLS:
                stored_approval_snapshot = _dict_argument(loads(approval.source_snapshot_json))
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
                        unit_of_work,
                        command.command_id,
                        response,
                        action.version,
                        now_ms,
                    )
                    unit_of_work.commit()
                    return response
                current_source_snapshot = {
                    **command.source_snapshot,
                    "calendar_conflict": stored_approval_snapshot.get("calendar_conflict"),
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
        self._nonce_lock = threading.Lock()

    def __call__(self, *, action_id: str, claim_token: str) -> ExecutedWriteActionResult:
        payload = read_claim_token(claim_token, signing_secret=self._signing_secret)
        if str(payload["service_instance_id"]) != self._service_instance_id:
            raise PermissionError("claim token service binding mismatch")
        if self._now_ms() >= _coerce_int(payload["expires_at_ms"]):
            raise PermissionError("claim token has expired")
        nonce = str(payload["nonce"])
        # Atomically check-and-reserve the nonce before doing anything else so
        # two concurrent callers holding the same claim token can never both
        # pass this gate, regardless of what happens to either request next.
        with self._nonce_lock:
            if nonce in self._used_nonces:
                raise PermissionError("claim token has already been used")
            self._used_nonces.add(nonce)

        try:
            with self._unit_of_work_factory() as unit_of_work:
                action = _require_action(unit_of_work, action_id)
                plan = _require_plan(unit_of_work, action.plan_id)
                run = _require_run(unit_of_work, plan.run_id)
                if run.status in {RunStatus.CANCEL_REQUESTED, RunStatus.CANCELLED}:
                    raise PermissionError("run cancellation forbids Google write dispatch")
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
        except Exception:
            # Nothing was dispatched: release the nonce so a legitimate retry
            # of this same claim token (e.g. a langgraph resume that re-runs
            # execution after a transient pre-dispatch validation failure) is
            # not permanently blocked by a claim that never reached Google.
            with self._nonce_lock:
                self._used_nonces.discard(nonce)
            raise

        final_arguments = _build_final_dispatch_arguments(
            action.tool_name,
            loads(action.arguments_json),
            recovery_fingerprint=approval.recovery_fingerprint,
        )
        claim_context = _prepare_gateway_claim_context(
            gateway=self._gateway,
            claim_payload=payload,
            tool_name=action.tool_name,
            approval_arguments_hash=action.arguments_hash,
            execution_arguments_hash=calculate_canonical_json_hash(final_arguments),
        )
        snapshot = _dispatch_write_action(
            self._gateway,
            action.tool_name,
            loads(action.arguments_json),
            recovery_fingerprint=approval.recovery_fingerprint,
            claim_context=claim_context,
        )
        return ExecutedWriteActionResult(
            snapshot=snapshot,
            response_metadata_json=dumps(
                {"operation": action.tool_name, "resource_id": snapshot.resource_id},
                sort_keys=True,
            ),
        )


class PreflightWriteActionService:
    """Read the approved target immediately before the claim transaction."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        gateway: GoogleWorkspaceGateway,
        now_ms: Callable[[], int] | None = None,
        work_hours_provider: Callable[[], CalendarWorkHours] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._gateway = gateway
        self._now_ms = now_ms or (lambda: time.time_ns() // 1_000_000)
        self._registry = build_p0_tool_registry()
        self._task_duplicates = TaskDuplicateValidator(gateway=gateway, now_ms=self._now_ms)
        self._calendar_conflicts = CalendarConflictValidator(
            gateway=gateway,
            now_ms=self._now_ms,
            work_hours_provider=work_hours_provider
            or (lambda: CalendarWorkHours(timezone="Asia/Seoul")),
        )

    def __call__(self, *, action_id: str) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            action = _require_action(unit_of_work, action_id)
            if action.status != ActionStatus.APPROVED.value:
                raise PolicyViolationError("write preflight requires an approved action")
            self._registry.require(action.tool_name)
            arguments = _dict_argument(loads(action.arguments_json))
            action_version = action.version
            arguments_hash = action.arguments_hash
            plan = _require_plan(unit_of_work, action.plan_id)
            approval = unit_of_work.approvals.get_active_by_action(action.id)
            if approval is None:
                raise PolicyViolationError("write preflight requires an active approval")
            approval_id = approval.id
            approval_snapshot = _dict_argument(loads(approval.source_snapshot_json))
            target_ref = (
                None
                if action.target_resource_ref_id is None
                else unit_of_work.resource_refs.get_by_id(action.target_resource_ref_id)
            )

        if action.tool_name == TASK_CREATE_TOOL:
            try:
                fresh_duplicate_risk = self._task_duplicates.fresh_risk(arguments)
            except Exception as error:
                with self._unit_of_work_factory() as unit_of_work:
                    current = _require_action(unit_of_work, action_id)
                    unit_of_work.audits.add(
                        _audit_event(
                            run_id=plan.run_id,
                            action_id=action_id,
                            event_type="TASK_DUPLICATE_PREFLIGHT_BLOCKED",
                            outcome="FAIL_CLOSED",
                            metadata={
                                "action_version": current.version,
                                "safe_error_code": (
                                    error.code.value
                                    if isinstance(error, GoogleWorkspaceGatewayError)
                                    else type(error).__name__
                                ),
                            },
                            created_at_ms=self._now_ms(),
                        )
                    )
                    unit_of_work.commit()
                raise

            must_reapprove = False
            with self._unit_of_work_factory() as unit_of_work:
                current = _require_action(unit_of_work, action_id)
                current_approval = unit_of_work.approvals.get_active_by_action(action_id)
                if (
                    current.status != ActionStatus.APPROVED.value
                    or current.version != action_version
                    or current.arguments_hash != arguments_hash
                    or current_approval is None
                    or current_approval.id != approval_id
                ):
                    raise PolicyViolationError(
                        "write action changed during task duplicate preflight"
                    )
                merged_risk = merge_duplicate_risk(current.risk, fresh_duplicate_risk)
                must_reapprove = duplicate_change_requires_reapproval(
                    approved=approval_duplicate_authority(approval_snapshot),
                    current=duplicate_authority(merged_risk),
                )
                now_ms = self._now_ms()
                if must_reapprove:
                    result = unit_of_work.actions.modify_write(
                        current.id,
                        expected_version=current.version,
                        updated_at_ms=now_ms,
                        arguments_json=current.arguments_json,
                        arguments_hash=current.arguments_hash,
                        risk=merged_risk,
                    )
                    if not result.applied:
                        raise PolicyViolationError(
                            "write action changed during task duplicate preflight"
                        )
                    unit_of_work.approvals.revoke_active_by_action(current.id)
                    unit_of_work.audits.add(
                        _audit_event(
                            run_id=plan.run_id,
                            action_id=current.id,
                            event_type="TASK_DUPLICATE_PREFLIGHT_BLOCKED",
                            outcome="REAPPROVAL_REQUIRED",
                            metadata={
                                "decision": (duplicate_authority(merged_risk) or ("UNKNOWN", ()))[
                                    0
                                ],
                                "matched_count": len(
                                    (duplicate_authority(merged_risk) or ("UNKNOWN", ()))[1]
                                ),
                            },
                            created_at_ms=now_ms,
                        )
                    )
                else:
                    unit_of_work.actions.update_risk_snapshot(
                        current.id,
                        expected_version=current.version,
                        updated_at_ms=now_ms,
                        risk=merged_risk,
                    )
                authority = duplicate_authority(merged_risk) or ("UNKNOWN", ())
                unit_of_work.audits.add(
                    _audit_event(
                        run_id=plan.run_id,
                        action_id=current.id,
                        event_type="TASK_DUPLICATE_CHECKED",
                        outcome=("BLOCKED" if must_reapprove else "ALLOWED"),
                        metadata={
                            "decision": authority[0],
                            "matched_count": len(authority[1]),
                            "freshness": "FRESH_GOOGLE_GET",
                        },
                        created_at_ms=now_ms,
                    )
                )
                unit_of_work.commit()
            if must_reapprove:
                raise PolicyViolationError(
                    "task duplicate result changed; acknowledgement and reapproval are required"
                )
            return

        if action.tool_name in CALENDAR_CONFLICT_TOOLS:
            try:
                fresh_conflict_risk = self._calendar_conflicts.fresh_risk(arguments)
            except Exception as error:
                with self._unit_of_work_factory() as unit_of_work:
                    current = _require_action(unit_of_work, action_id)
                    unit_of_work.audits.add(
                        _audit_event(
                            run_id=plan.run_id,
                            action_id=action_id,
                            event_type="CALENDAR_CONFLICT_PREFLIGHT_BLOCKED",
                            outcome="FAIL_CLOSED",
                            metadata={
                                "action_version": current.version,
                                "safe_error_code": (
                                    error.code.value
                                    if isinstance(error, GoogleWorkspaceGatewayError)
                                    else type(error).__name__
                                ),
                            },
                            created_at_ms=self._now_ms(),
                        )
                    )
                    unit_of_work.commit()
                raise

            must_reapprove = False
            with self._unit_of_work_factory() as unit_of_work:
                current = _require_action(unit_of_work, action_id)
                current_approval = unit_of_work.approvals.get_active_by_action(action_id)
                if (
                    current.status != ActionStatus.APPROVED.value
                    or current.version != action_version
                    or current.arguments_hash != arguments_hash
                    or current_approval is None
                    or current_approval.id != approval_id
                ):
                    raise PolicyViolationError(
                        "write action changed during calendar conflict preflight"
                    )
                merged_risk = merge_calendar_conflict_risk(current.risk, fresh_conflict_risk)
                must_reapprove = calendar_conflict_change_requires_reapproval(
                    approved=approval_calendar_conflict_authority(approval_snapshot),
                    current=calendar_conflict_authority(merged_risk),
                )
                now_ms = self._now_ms()
                if must_reapprove:
                    result = unit_of_work.actions.modify_write(
                        current.id,
                        expected_version=current.version,
                        updated_at_ms=now_ms,
                        arguments_json=current.arguments_json,
                        arguments_hash=current.arguments_hash,
                        risk=merged_risk,
                    )
                    if not result.applied:
                        raise PolicyViolationError(
                            "write action changed during calendar conflict preflight"
                        )
                    unit_of_work.approvals.revoke_active_by_action(current.id)
                else:
                    unit_of_work.actions.update_risk_snapshot(
                        current.id,
                        expected_version=current.version,
                        updated_at_ms=now_ms,
                        risk=merged_risk,
                    )
                unit_of_work.audits.add(
                    _audit_event(
                        run_id=plan.run_id,
                        action_id=current.id,
                        event_type="CALENDAR_CONFLICT_CHECKED",
                        outcome="REAPPROVAL_REQUIRED" if must_reapprove else "ALLOWED",
                        metadata={
                            **_calendar_conflict_audit_metadata(
                                risk=merged_risk, action_id=current.id
                            ),
                        },
                        created_at_ms=now_ms,
                    )
                )
                unit_of_work.commit()
            if must_reapprove:
                raise PolicyViolationError(
                    "calendar conflict result changed; acknowledgement and reapproval are required"
                )
            return

        if action.tool_name == "gmail_send":
            draft_id = _required_argument_string(arguments, "draft_id")
            draft = self._gateway.get_gmail_draft(draft_id=draft_id)
            _validate_preflight_target(
                snapshot=draft,
                target_ref=None,
                expected_resource_type=ResourceType.GMAIL_DRAFT,
                expected_parent_id=None,
            )
            return
        if action.tool_name == "calendar_delete_event":
            calendar_id = _required_argument_string(arguments, "calendar_id")
            event_id = _required_argument_string(arguments, "event_id")
            if arguments.get("delete_scope") not in {None, "SINGLE"}:
                raise PolicyViolationError("calendar recurring series deletion is forbidden")
            event = self._gateway.get_calendar_event(calendar_id=calendar_id, event_id=event_id)
            if (
                event.payload.get("recurring_event_id") is not None
                and arguments.get("delete_scope") != "SINGLE"
            ):
                raise PolicyViolationError("recurring event series deletion is forbidden")
            _validate_preflight_target(
                snapshot=event,
                target_ref=target_ref,
                expected_resource_type=ResourceType.CALENDAR_EVENT,
                expected_parent_id=calendar_id,
            )
        if action.tool_name == "tasks_delete_task":
            task_list_id = _required_argument_string(arguments, "task_list_id")
            task_id = _required_argument_string(arguments, "task_id")
            task = self._gateway.get_task(task_list_id=task_list_id, task_id=task_id)
            _validate_preflight_target(
                snapshot=task,
                target_ref=target_ref,
                expected_resource_type=ResourceType.TASK,
                expected_parent_id=task_list_id,
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
            persisted_resource_ref = _upsert_resource_ref(
                unit_of_work=unit_of_work,
                resource_ref=resource_ref,
            )
            unit_of_work.execution_attempts.mark_succeeded(
                attempt.id,
                expected_version=command.expected_attempt_version,
                result_resource_ref_id=persisted_resource_ref.id,
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
                        {"attempt_id": attempt.id, "resource_ref_id": persisted_resource_ref.id},
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
            _propagate_dependency_blocked(
                unit_of_work=unit_of_work,
                action_id=action.id,
                run_id=plan.run_id,
                updated_at_ms=now_ms,
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


class MarkWriteActionUnknownResultService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: MarkWriteActionUnknownResultCommand) -> WriteActionResponse:
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
                command_type="MarkWriteActionUnknownResult",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            unit_of_work.execution_attempts.mark_unknown_result(
                attempt.id,
                expected_version=command.expected_attempt_version,
                error_code=command.error_code,
                error_detail_json=dumps({"detail": command.error_detail}, sort_keys=True),
                finished_at_ms=now_ms,
            )
            result = unit_of_work.actions.mark_unknown_result(
                action.id,
                expected_version=command.expected_action_version,
                updated_at_ms=now_ms,
            )
            if not result.applied:
                raise RuntimeError(
                    "write action mark_unknown_result transition failed after attempt update"
                )
            run = unit_of_work.runs.set_recovery_required(plan.run_id)
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_UNKNOWN_RESULT",
                    status=ActionStatus.UNKNOWN_RESULT.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {
                            "attempt_id": attempt.id,
                            "error_code": command.error_code,
                            "run_status": run.status.value,
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_UNKNOWN_RESULT",
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
        gateway: VerificationSnapshotGateway,
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

            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            if attempt.status is not ExecutionAttemptStatus.SUCCEEDED:
                now_ms = self._now_ms()
                unit_of_work.command_receipts.add_received(
                    command_id=command.command_id,
                    command_type="VerifyWriteAction",
                    request_hash=command.request_hash,
                    aggregate_type="Action",
                    aggregate_id=command.action_id,
                    created_at_ms=now_ms,
                )
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
            fallback_resource_id = _resolve_snapshot_fallback_resource_id(
                unit_of_work,
                action=action,
                resource_ref_id=attempt.result_resource_ref_id,
            )

        delete_target_absent = False
        if action.tool_name in _DELETE_TOOL_TARGETS:
            try:
                actual_snapshot = _load_verification_snapshot(
                    gateway=self._gateway,
                    action=action,
                    fallback_resource_id=fallback_resource_id,
                )
            except LookupError:
                delete_target_absent = True
                actual_snapshot = None
            except GoogleWorkspaceGatewayError as error:
                if error.code is not GoogleWorkspaceErrorCode.NOT_FOUND:
                    raise
                delete_target_absent = True
                actual_snapshot = None
        else:
            actual_snapshot = _load_verification_snapshot(
                gateway=self._gateway,
                action=action,
                fallback_resource_id=fallback_resource_id,
            )

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

            expected = loads(action.expected_json)
            if action.tool_name in _DELETE_TOOL_TARGETS:
                delete_resource_type, delete_id_field, _delete_parent_field = _DELETE_TOOL_TARGETS[
                    action.tool_name
                ]
                actual_projection: dict[str, object] = {
                    "resource_type": delete_resource_type.value,
                    "resource_id": _required_argument_string(
                        _dict_argument(loads(action.arguments_json)), delete_id_field
                    ),
                    "absent": delete_target_absent,
                }
                diff = (
                    []
                    if delete_target_absent
                    else [{"path": "$.absent", "expected": True, "actual": False}]
                )
                verification_status = (
                    VerificationStatus.VERIFIED
                    if delete_target_absent
                    else VerificationStatus.MISMATCH
                )
            else:
                if actual_snapshot is None:
                    raise RuntimeError("verification snapshot is required")
                actual_projection = normalize_verification_projection(actual_snapshot)
                diff = calculate_verification_diff(expected, actual_projection)
                verification_status = (
                    VerificationStatus.VERIFIED if len(diff) == 0 else VerificationStatus.MISMATCH
                )
            verification_no = len(unit_of_work.verifications.list_by_attempt(attempt.id)) + 1
            result = unit_of_work.actions.store_verification(
                action.id,
                expected_version=command.expected_action_version,
                updated_at_ms=now_ms,
                verification_status=verification_status.value,
            )
            if not result.applied:
                response = _action_response_from_result(action_id=action.id, result=result)
                _finish_json_receipt(
                    unit_of_work,
                    command.command_id,
                    response,
                    result.current_version,
                    now_ms,
                )
                unit_of_work.commit()
                return response

            verification = VerificationRecord(
                id=command.verification_id,
                execution_attempt_id=attempt.id,
                verification_no=verification_no,
                status=verification_status,
                normalizer_version=VERIFICATION_NORMALIZER_VERSION,
                expected_json=canonicalize_json_value(expected),
                actual_json=canonicalize_json_value(actual_projection),
                diff_json=canonicalize_json_value(diff),
                verified_at_ms=now_ms,
            )
            unit_of_work.verifications.insert(verification)
            if verification_status is VerificationStatus.MISMATCH:
                _propagate_dependency_blocked(
                    unit_of_work=unit_of_work,
                    action_id=action.id,
                    run_id=plan.run_id,
                    updated_at_ms=now_ms,
                )
                # A persisted mismatch is an immutable external fact; only an explicit
                # recovery decision may choose the next run transition.
                unit_of_work.runs.set_recovery_required(plan.run_id)

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


class RecoverExistingWriteResultService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: RecoverExistingWriteResultCommand) -> WriteActionResponse:
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
                command_type="RecoverExistingWriteResult",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            if action.version != command.expected_action_version:
                response = _write_action_version_conflict_response(
                    action=action,
                    attempt_id=attempt.id,
                    conflict_detail="expected_action_version does not match current_version",
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
            if attempt.version != command.expected_attempt_version:
                response = _write_action_version_conflict_response(
                    action=action,
                    attempt_id=attempt.id,
                    conflict_detail="expected_attempt_version does not match current_version",
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
            resource_ref = _resource_ref_from_snapshot(
                run_id=plan.run_id,
                snapshot=command.snapshot,
                captured_at_ms=now_ms,
            )
            persisted_resource_ref = _upsert_resource_ref(
                unit_of_work=unit_of_work,
                resource_ref=resource_ref,
            )
            unit_of_work.execution_attempts.update_status(
                attempt.id,
                expected_version=command.expected_attempt_version,
                status=ExecutionAttemptStatus.SUCCEEDED,
                error_code=command.safe_error_code,
                error_detail_json=None,
                result_resource_ref_id=persisted_resource_ref.id,
                response_metadata_json=dumps(
                    {"operation": action.tool_name, "resource_id": command.snapshot.resource_id},
                    sort_keys=True,
                ),
                finished_at_ms=now_ms,
            )
            result = unit_of_work.actions.recover_existing_result(
                action.id,
                expected_version=command.expected_action_version,
                updated_at_ms=now_ms,
            )
            if not result.applied:
                raise RuntimeError("recover_existing_result action transition failed")
            unit_of_work.runs.set_verifying(plan.run_id)
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_RECOVERED",
                    status=ActionStatus.EXECUTED.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"attempt_id": attempt.id, "resource_ref_id": persisted_resource_ref.id},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_RECOVERED",
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


class ResolveUnknownWriteAsFailedService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: ResolveUnknownWriteAsFailedCommand) -> WriteActionResponse:
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
                command_type="ResolveUnknownWriteAsFailed",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            if action.version != command.expected_action_version:
                response = _write_action_version_conflict_response(
                    action=action,
                    attempt_id=attempt.id,
                    conflict_detail="expected_action_version does not match current_version",
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
            if attempt.version != command.expected_attempt_version:
                response = _write_action_version_conflict_response(
                    action=action,
                    attempt_id=attempt.id,
                    conflict_detail="expected_attempt_version does not match current_version",
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
            unit_of_work.execution_attempts.update_status(
                attempt.id,
                expected_version=command.expected_attempt_version,
                status=ExecutionAttemptStatus.FAILED,
                error_code=command.error_code,
                error_detail_json=dumps({"detail": command.error_detail}, sort_keys=True),
                result_resource_ref_id=None,
                response_metadata_json=None,
                finished_at_ms=now_ms,
            )
            result = unit_of_work.actions.resolve_unknown_as_failed(
                action.id,
                expected_version=command.expected_action_version,
                updated_at_ms=now_ms,
            )
            if not result.applied:
                raise RuntimeError("resolve_unknown_as_failed action transition failed")
            _propagate_dependency_blocked(
                unit_of_work=unit_of_work,
                action_id=action.id,
                run_id=plan.run_id,
                updated_at_ms=now_ms,
            )
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_UNKNOWN_RESOLVED_FAILED",
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
                    event_type="WRITE_RECOVERY_RESOLVED_FAILED",
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


class RecoverUnknownCreateActionService:
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

    def __call__(self, command: RecoverUnknownCreateActionCommand) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            approval = _require_approval(unit_of_work, attempt.approval_id)
        candidates = self._gateway.search_by_recovery_fingerprint(
            resource_type=_recovery_resource_type_for_tool(action.tool_name),
            recovery_fingerprint=approval.recovery_fingerprint,
        )
        if len(candidates) != 1:
            return WriteActionResponse(
                applied=False,
                result_code=ResultCode.RECOVERY_REQUIRED.value,
                action_id=action.id,
                action_status=action.status,
                action_version=action.version,
                next_allowed_commands=(),
                attempt_id=attempt.id,
                conflict_detail="recovery search did not resolve to exactly one candidate",
            )
        return RecoverExistingWriteResultService(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
        )(
            RecoverExistingWriteResultCommand(
                command_id=command.command_id,
                request_hash=command.request_hash,
                action_id=command.action_id,
                attempt_id=command.attempt_id,
                expected_action_version=command.expected_action_version,
                expected_attempt_version=command.expected_attempt_version,
                snapshot=candidates[0],
            )
        )


class RecoverUnknownSendActionService:
    """Recover an uncertain send by locating the existing sent message only."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        gateway: GoogleWorkspaceGateway,
    ) -> None:
        self._delegate = RecoverUnknownCreateActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            gateway=gateway,
        )

    def __call__(self, command: RecoverUnknownSendActionCommand) -> WriteActionResponse:
        return self._delegate(
            RecoverUnknownCreateActionCommand(
                command_id=command.command_id,
                request_hash=command.request_hash,
                action_id=command.action_id,
                attempt_id=command.attempt_id,
                expected_action_version=command.expected_action_version,
                expected_attempt_version=command.expected_attempt_version,
            )
        )


class RecoverUnknownDeleteActionService:
    """Reconcile an uncertain delete through target absence, never another delete call."""

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

    def __call__(self, command: RecoverUnknownDeleteActionCommand) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            if action.tool_name not in _DELETE_TOOL_TARGETS:
                raise PolicyViolationError(
                    f"delete recovery requires a registered GET_ABSENT delete tool, "
                    f"got: {action.tool_name}"
                )
            arguments = _dict_argument(loads(action.arguments_json))
        try:
            self._get_delete_target(tool_name=action.tool_name, arguments=arguments)
        except LookupError:
            return self._recover_absent_target(command=command, action=action, attempt=attempt)
        except GoogleWorkspaceGatewayError as error:
            if error.code is not GoogleWorkspaceErrorCode.NOT_FOUND:
                raise
            return self._recover_absent_target(command=command, action=action, attempt=attempt)
        return WriteActionResponse(
            applied=False,
            result_code=ResultCode.RECOVERY_REQUIRED.value,
            action_id=action.id,
            action_status=action.status,
            action_version=action.version,
            next_allowed_commands=(),
            attempt_id=attempt.id,
            conflict_detail="delete target is still present; blind re-delete is forbidden",
        )

    def _get_delete_target(
        self, *, tool_name: str, arguments: dict[str, object]
    ) -> ResourceSnapshot:
        if tool_name == "calendar_delete_event":
            return self._gateway.get_calendar_event(
                calendar_id=_required_argument_string(arguments, "calendar_id"),
                event_id=_required_argument_string(arguments, "event_id"),
            )
        if tool_name == "tasks_delete_task":
            return self._gateway.get_task(
                task_list_id=_required_argument_string(arguments, "task_list_id"),
                task_id=_required_argument_string(arguments, "task_id"),
            )
        raise LookupError(f"unsupported delete recovery tool: {tool_name}")

    def _recover_absent_target(
        self,
        *,
        command: RecoverUnknownDeleteActionCommand,
        action: ActionRecord,
        attempt: ExecutionAttemptRecord,
    ) -> WriteActionResponse:
        arguments = _dict_argument(loads(action.arguments_json))
        resource_type, id_field, parent_field = _DELETE_TOOL_TARGETS[action.tool_name]
        parent_id = _required_argument_string(arguments, parent_field)
        snapshot = ResourceSnapshot(
            fixture_snapshot_id="recovery-absence",
            resource_type=resource_type,
            resource_id=_required_argument_string(arguments, id_field),
            parent_id=parent_id,
            related_resource_ids=(parent_id,),
            version="deleted",
            recovery_fingerprint=None,
            payload={"deleted": True},
        )
        return RecoverExistingWriteResultService(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
        )(
            RecoverExistingWriteResultCommand(
                command_id=command.command_id,
                request_hash=command.request_hash,
                action_id=command.action_id,
                attempt_id=command.attempt_id,
                expected_action_version=command.expected_action_version,
                expected_attempt_version=command.expected_attempt_version,
                snapshot=snapshot,
            )
        )


class RecoverUnknownUpdateActionService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        gateway: VerificationSnapshotGateway,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._gateway = gateway

    def __call__(self, command: RecoverUnknownUpdateActionCommand) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _resolve_existing_action_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                )
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            approval = _require_approval(unit_of_work, attempt.approval_id)
            fallback_resource_id = _resolve_snapshot_fallback_resource_id(
                unit_of_work,
                action=action,
                resource_ref_id=action.target_resource_ref_id,
            )
        snapshot = _load_verification_snapshot(
            gateway=self._gateway,
            action=action,
            fallback_resource_id=fallback_resource_id,
        )
        normalized_actual = normalize_verification_projection(snapshot)
        expected_projection = cast(dict[str, object], loads(action.expected_json))
        if normalized_actual == expected_projection:
            return RecoverExistingWriteResultService(
                unit_of_work_factory=self._unit_of_work_factory,
                now_ms=self._now_ms,
            )(
                RecoverExistingWriteResultCommand(
                    command_id=command.command_id,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                    attempt_id=command.attempt_id,
                    expected_action_version=command.expected_action_version,
                    expected_attempt_version=command.expected_attempt_version,
                    snapshot=snapshot,
                )
            )
        source_snapshot = cast(dict[str, object], loads(approval.source_snapshot_json))
        if normalized_actual == source_snapshot:
            return ResolveUnknownWriteAsFailedService(
                unit_of_work_factory=self._unit_of_work_factory,
                now_ms=self._now_ms,
            )(
                ResolveUnknownWriteAsFailedCommand(
                    command_id=command.command_id,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                    attempt_id=command.attempt_id,
                    expected_action_version=command.expected_action_version,
                    expected_attempt_version=command.expected_attempt_version,
                    error_code=GoogleWorkspaceErrorCode.NO_RECOVERY_CANDIDATE.value,
                    error_detail="target snapshot still matches source snapshot",
                )
            )
        return WriteActionResponse(
            applied=False,
            result_code=ResultCode.RECOVERY_REQUIRED.value,
            action_id=action.id,
            action_status=action.status,
            action_version=action.version,
            next_allowed_commands=(),
            attempt_id=attempt.id,
            conflict_detail="update recovery requires manual resolution",
        )


class PrepareWriteRetryService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: PrepareWriteRetryCommand) -> WriteActionResponse:
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
                command_type="PrepareWriteRetry",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            result = unit_of_work.actions.prepare_write_retry(
                action.id,
                expected_version=command.expected_action_version,
                updated_at_ms=now_ms,
            )
            if not result.applied:
                response = _action_response_from_result(action_id=action.id, result=result)
                _finish_json_receipt(
                    unit_of_work,
                    command.command_id,
                    response,
                    result.current_version,
                    now_ms,
                )
                unit_of_work.commit()
                return response
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_RETRY_PREPARED",
                    status=ActionStatus.MODIFIED.value,
                    duration_ms=None,
                    payload_json=dumps({"action_id": action.id}, sort_keys=True),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_RETRY_PREPARED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"action_id": action.id},
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


class RequestRunCancellationService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: RequestRunCancellationCommand) -> WriteRunResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _resolve_existing_run_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    run_id=command.run_id,
                )
            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="RequestRunCancellation",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            run = _require_run(unit_of_work, command.run_id)
            plans = unit_of_work.plans.list_by_run(run.id)
            plan = max(plans, key=lambda item: (item.revision_no, item.created_at_ms), default=None)
            actions = () if plan is None else unit_of_work.actions.list_by_plan(plan.id)
            cancel_result = unit_of_work.runs.request_cancel(
                run.id,
                expected_version=command.expected_run_version,
            )
            if not cancel_result.applied:
                response = WriteRunResponse(
                    applied=False,
                    result_code=cancel_result.result_code.value,
                    run_id=run.id,
                    run_status=cancel_result.current_status.value,
                    run_version=cancel_result.current_version,
                    plan_id=None if plan is None else plan.id,
                    plan_status=None if plan is None else plan.status.value,
                    conflict_detail=cancel_result.conflict_detail,
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run.version, now_ms
                )
                unit_of_work.commit()
                return response
            has_started_write = any(
                action.status
                in {
                    ActionStatus.EXECUTING.value,
                    ActionStatus.UNKNOWN_RESULT.value,
                    ActionStatus.EXECUTED.value,
                    ActionStatus.VERIFIED.value,
                }
                for action in actions
            )
            if not has_started_write:
                for action in actions:
                    if action.status in {
                        ActionStatus.PROPOSED.value,
                        ActionStatus.MODIFIED.value,
                        ActionStatus.APPROVED.value,
                        ActionStatus.EXPIRED.value,
                    }:
                        if action.status == ActionStatus.APPROVED.value:
                            unit_of_work.approvals.revoke_active_by_action(action.id)
                        unit_of_work.actions.cancel_pending(
                            action.id,
                            expected_version=action.version,
                            updated_at_ms=now_ms,
                        )
                if plan is not None:
                    unit_of_work.plans.cancel(plan.id)
                final_result = unit_of_work.runs.finalize_cancel(
                    run.id,
                    expected_version=cancel_result.current_version,
                    finished_at_ms=now_ms,
                )
                response = WriteRunResponse(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED.value,
                    run_id=run.id,
                    run_status=final_result.current_status.value,
                    run_version=final_result.current_version,
                    plan_id=None if plan is None else plan.id,
                    plan_status=None if plan is None else PlanStatus.CANCELLED.value,
                    result_kind="CANCELLED",
                )
            else:
                response = WriteRunResponse(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED.value,
                    run_id=run.id,
                    run_status=cancel_result.current_status.value,
                    run_version=cancel_result.current_version,
                    plan_id=None if plan is None else plan.id,
                    plan_status=None if plan is None else plan.status.value,
                    result_kind="CANCEL_REQUESTED",
                )
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=run.id,
                    action_id=None,
                    event_type="RUN_CANCELLATION_REQUESTED",
                    status=response.run_status,
                    duration_ms=None,
                    payload_json=dumps(
                        {"plan_id": None if plan is None else plan.id}, sort_keys=True
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=run.id,
                    action_id=None,
                    event_type="RUN_CANCELLATION_REQUESTED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"plan_id": None if plan is None else plan.id},
                    created_at_ms=now_ms,
                )
            )
            _finish_json_receipt(
                unit_of_work,
                command.command_id,
                response,
                response.run_version,
                now_ms,
            )
            unit_of_work.commit()
            return response


class FinalizeRunCancellationService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: FinalizeRunCancellationCommand) -> WriteRunResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _resolve_existing_run_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    run_id=command.run_id,
                )
            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="FinalizeRunCancellation",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            run = _require_run(unit_of_work, command.run_id)
            plan = _require_latest_plan_for_run(unit_of_work, run.id)
            actions = unit_of_work.actions.list_by_plan(plan.id)
            if command.expected_run_version != run.version:
                response = WriteRunResponse(
                    applied=False,
                    result_code=ResultCode.VERSION_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail="expected_run_version does not match current version",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run.version, now_ms
                )
                unit_of_work.commit()
                return response
            finalize_expected_version = command.expected_run_version
            if run.status is RunStatus.VERIFYING:
                if not _has_successful_cancel_marker(unit_of_work, run.id):
                    response = WriteRunResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        run_id=run.id,
                        run_status=run.status.value,
                        run_version=run.version,
                        plan_id=plan.id,
                        plan_status=plan.status.value,
                        conflict_detail=(
                            "verification can continue cancellation only after a successful "
                            "cancel request"
                        ),
                    )
                    _finish_json_receipt(
                        unit_of_work, command.command_id, response, run.version, now_ms
                    )
                    unit_of_work.commit()
                    return response
                continued_cancel = unit_of_work.runs.request_cancel(
                    run.id,
                    expected_version=run.version,
                )
                if not continued_cancel.applied:
                    response = WriteRunResponse(
                        applied=False,
                        result_code=continued_cancel.result_code.value,
                        run_id=run.id,
                        run_status=continued_cancel.current_status.value,
                        run_version=continued_cancel.current_version,
                        plan_id=plan.id,
                        plan_status=plan.status.value,
                        conflict_detail=continued_cancel.conflict_detail,
                    )
                    _finish_json_receipt(
                        unit_of_work,
                        command.command_id,
                        response,
                        continued_cancel.current_version,
                        now_ms,
                    )
                    unit_of_work.commit()
                    return response
                finalize_expected_version = continued_cancel.current_version
                run = _require_run(unit_of_work, command.run_id)
            elif run.status is not RunStatus.CANCEL_REQUESTED:
                response = WriteRunResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail="cancellation finalization requires cancel-requested state",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run.version, now_ms
                )
                unit_of_work.commit()
                return response
            if any(action.status == ActionStatus.UNKNOWN_RESULT.value for action in actions):
                recovery_run = unit_of_work.runs.set_recovery_required(run.id)
                response = WriteRunResponse(
                    applied=False,
                    result_code=ResultCode.RECOVERY_REQUIRED.value,
                    run_id=run.id,
                    run_status=recovery_run.status.value,
                    run_version=recovery_run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    result_kind="RECOVERY_REQUIRED",
                    conflict_detail="unknown write results must be resolved before cancellation",
                )
            elif any(action.status == ActionStatus.EXECUTING.value for action in actions):
                response = WriteRunResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail="cannot finalize cancellation while write is executing",
                )
            elif any(action.status == ActionStatus.EXECUTED.value for action in actions):
                updated_run = unit_of_work.runs.set_verifying(run.id)
                response = WriteRunResponse(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED.value,
                    run_id=run.id,
                    run_status=updated_run.status.value,
                    run_version=updated_run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                )
            else:
                _cancel_pending_actions(
                    unit_of_work=unit_of_work,
                    plan_id=plan.id,
                    updated_at_ms=now_ms,
                )
                final_result = unit_of_work.runs.finalize_cancel(
                    run.id,
                    expected_version=finalize_expected_version,
                    finished_at_ms=now_ms,
                )
                if not final_result.applied:
                    raise RuntimeError("validated cancellation finalization was not applied")
                unit_of_work.plans.cancel(plan.id)
                response = WriteRunResponse(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED.value,
                    run_id=run.id,
                    run_status=final_result.current_status.value,
                    run_version=final_result.current_version,
                    plan_id=plan.id,
                    plan_status=PlanStatus.CANCELLED.value,
                    result_kind=(
                        "PARTIAL"
                        if any(action.status == ActionStatus.VERIFIED.value for action in actions)
                        else "CANCELLED"
                    ),
                )
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=run.id,
                    action_id=None,
                    event_type="RUN_CANCELLATION_FINALIZED",
                    status=response.run_status,
                    duration_ms=None,
                    payload_json=dumps({"result_kind": response.result_kind}, sort_keys=True),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=run.id,
                    action_id=None,
                    event_type="RUN_CANCELLATION_FINALIZED",
                    outcome=response.result_code,
                    metadata={"result_kind": response.result_kind},
                    created_at_ms=now_ms,
                )
            )
            _finish_json_receipt(
                unit_of_work, command.command_id, response, response.run_version, now_ms
            )
            unit_of_work.commit()
            return response


class ResolveMismatchRecoveryService:
    """Resolve an immutable verification mismatch without reusing write authority."""

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: ResolveMismatchRecoveryCommand) -> WriteRunResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _resolve_existing_run_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    run_id=command.run_id,
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="ResolveMismatchRecovery",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            run = _require_run(unit_of_work, command.run_id)
            action = _require_action(unit_of_work, command.action_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            if plan.run_id != run.id or action.status != ActionStatus.MISMATCH.value:
                response = WriteRunResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail="recovery requires a MISMATCH action owned by the run",
                )
                return _finish_recovery_response(
                    unit_of_work=unit_of_work,
                    command_id=command.command_id,
                    response=response,
                    now_ms=now_ms,
                )

            next_status = (
                RunStatus.COMPLETED
                if command.resolution_kind is RecoveryResolutionKind.ACCEPT_PARTIAL
                else RunStatus.PLANNING
            )
            resolved = unit_of_work.runs.resolve_recovery(
                run.id,
                expected_version=command.expected_run_version,
                recovery_next_status=next_status,
                finished_at_ms=now_ms if next_status is RunStatus.COMPLETED else None,
            )
            if not resolved.applied:
                response = WriteRunResponse(
                    applied=False,
                    result_code=resolved.result_code.value,
                    run_id=run.id,
                    run_status=resolved.current_status.value,
                    run_version=resolved.current_version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail=resolved.conflict_detail,
                )
                return _finish_recovery_response(
                    unit_of_work=unit_of_work,
                    command_id=command.command_id,
                    response=response,
                    now_ms=now_ms,
                )

            if command.resolution_kind is RecoveryResolutionKind.ACCEPT_PARTIAL:
                _cancel_pending_actions(
                    unit_of_work=unit_of_work,
                    plan_id=plan.id,
                    updated_at_ms=now_ms,
                )
                unit_of_work.plans.complete(plan.id)
                result_plan = plan.id
                result_plan_status = PlanStatus.COMPLETED.value
                result_kind = "PARTIAL"
            else:
                if not command.corrective_plan_id:
                    raise ValueError("corrective_plan_id is required for CREATE_CORRECTIVE_PLAN")
                unit_of_work.plans.supersede(plan.id)
                next_revision = (
                    max(item.revision_no for item in unit_of_work.plans.list_by_run(run.id)) + 1
                )
                corrective_plan = PlanRecord(
                    id=command.corrective_plan_id,
                    run_id=run.id,
                    revision_no=next_revision,
                    status=PlanStatus.DRAFT,
                    summary_text=f"Corrective plan for mismatch action {action.id}",
                    created_at_ms=now_ms,
                )
                unit_of_work.plans.insert_draft(corrective_plan)
                result_plan = corrective_plan.id
                result_plan_status = corrective_plan.status.value
                result_kind = "CORRECTIVE_PLAN_REQUIRED"

            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=run.id,
                    action_id=action.id,
                    event_type="RECOVERY_RESOLVED",
                    status=resolved.current_status.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"resolution_kind": command.resolution_kind.value}, sort_keys=True
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=run.id,
                    action_id=action.id,
                    event_type="RECOVERY_RESOLVED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"resolution_kind": command.resolution_kind.value},
                    created_at_ms=now_ms,
                )
            )
            response = WriteRunResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                run_id=run.id,
                run_status=resolved.current_status.value,
                run_version=resolved.current_version,
                plan_id=result_plan,
                plan_status=result_plan_status,
                result_kind=result_kind,
            )
            return _finish_recovery_response(
                unit_of_work=unit_of_work,
                command_id=command.command_id,
                response=response,
                now_ms=now_ms,
            )


class RequireWriteReauthService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: RequireWriteReauthCommand) -> WriteRunResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _resolve_existing_run_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    run_id=command.run_id,
                )
            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="RequireWriteReauth",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            updated_run = unit_of_work.runs.set_reauth_required(command.run_id)
            plan = _require_latest_plan_for_run(unit_of_work, command.run_id)
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=command.run_id,
                    action_id=command.action_id,
                    event_type="RUN_REAUTH_REQUIRED",
                    status=updated_run.status.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"safe_error_code": command.safe_error_code},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=command.run_id,
                    action_id=command.action_id,
                    event_type="RUN_REAUTH_REQUIRED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"safe_error_code": command.safe_error_code},
                    created_at_ms=now_ms,
                )
            )
            response = WriteRunResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                run_id=command.run_id,
                run_status=updated_run.status.value,
                run_version=updated_run.version,
                plan_id=plan.id,
                plan_status=plan.status.value,
                result_kind="REAUTH_REQUIRED",
            )
            _finish_json_receipt(
                unit_of_work, command.command_id, response, response.run_version, now_ms
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
    payload = dict(snapshot.payload)
    payload.pop("recovery_fingerprint", None)
    return {
        "resource_type": snapshot.resource_type.value,
        "resource_id": snapshot.resource_id,
        "parent_id": snapshot.parent_id,
        "version": snapshot.version,
        "payload": payload,
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
        canonicalize_action_risk(action.risk)
        entry = registry.require(action.tool_name)
        if entry.effect_type is EffectType.READ:
            raise ValueError(f"write plan cannot contain read-only tool: {action.tool_name}")
        validate_evidence_policy(
            policy_input=EvidencePolicyInput(
                evidence_count=evidence_count,
                requires_existing_resource=entry.effect_type
                in {EffectType.UPDATE, EffectType.DELETE},
                has_user_selected_resource=action.target_resource_ref_id is not None,
                has_explicit_resource_relation=action.target_resource_ref_id is not None,
            )
        )


def _build_final_dispatch_arguments(
    tool_name: str,
    arguments: dict[str, object],
    *,
    recovery_fingerprint: str | None,
) -> dict[str, object]:
    """Build the exact argument dict a write tool call dispatches with.

    ``ExecuteWriteActionService`` also canonicalizes this same dict to
    compute ClaimContextV2's ``execution_arguments_hash``, so it must stay
    byte-for-byte identical to what ``_dispatch_write_action`` sends to the
    gateway/MCP tool below.
    """

    if tool_name == "gmail_send":
        return {
            "draft_id": _required_argument_string(arguments, "draft_id"),
            "recovery_fingerprint": recovery_fingerprint,
        }
    if tool_name == "calendar_delete_event":
        return {
            "calendar_id": _required_argument_string(arguments, "calendar_id"),
            "event_id": _required_argument_string(arguments, "event_id"),
        }
    if tool_name == "tasks_delete_task":
        return {
            "task_list_id": _required_argument_string(arguments, "task_list_id"),
            "task_id": _required_argument_string(arguments, "task_id"),
        }
    payload = _dict_argument(arguments.get("payload"))
    payload_with_recovery = dict(payload)
    if recovery_fingerprint is not None and tool_name in {
        "gmail_create_draft",
        "tasks_create_task",
        "calendar_create_event",
    }:
        payload_with_recovery["recovery_fingerprint"] = recovery_fingerprint
    if tool_name == "gmail_create_draft":
        return {"payload": payload_with_recovery}
    if tool_name == "gmail_update_draft":
        return {"draft_id": str(arguments["draft_id"]), "payload": payload}
    if tool_name == "tasks_create_task":
        return {
            "task_list_id": str(arguments["task_list_id"]),
            "payload": payload_with_recovery,
        }
    if tool_name == "tasks_update_task":
        return {
            "task_list_id": str(arguments["task_list_id"]),
            "task_id": str(arguments["task_id"]),
            "payload": payload,
        }
    if tool_name == "calendar_create_event":
        return {
            "calendar_id": str(arguments["calendar_id"]),
            "payload": payload_with_recovery,
        }
    if tool_name == "calendar_update_event":
        return {
            "calendar_id": str(arguments["calendar_id"]),
            "event_id": str(arguments["event_id"]),
            "payload": payload,
        }
    raise LookupError(f"unsupported write tool: {tool_name}")


def _dispatch_write_action(
    gateway: GoogleWorkspaceGateway,
    tool_name: str,
    arguments: dict[str, object],
    *,
    recovery_fingerprint: str | None = None,
    claim_context: dict[str, object] | None = None,
) -> ResourceSnapshot:
    final_arguments = _build_final_dispatch_arguments(
        tool_name, arguments, recovery_fingerprint=recovery_fingerprint
    )
    if tool_name == "gmail_send":
        return gateway.send_gmail(
            draft_id=cast(str, final_arguments["draft_id"]),
            recovery_fingerprint=cast(str | None, final_arguments["recovery_fingerprint"]),
            claim_context=claim_context,
        )
    if tool_name == "calendar_delete_event":
        return gateway.delete_calendar_event(
            calendar_id=cast(str, final_arguments["calendar_id"]),
            event_id=cast(str, final_arguments["event_id"]),
            claim_context=claim_context,
        )
    if tool_name == "tasks_delete_task":
        return gateway.delete_task(
            task_list_id=cast(str, final_arguments["task_list_id"]),
            task_id=cast(str, final_arguments["task_id"]),
            claim_context=claim_context,
        )
    if tool_name == "gmail_create_draft":
        return gateway.create_gmail_draft(
            payload=cast(dict[str, object], final_arguments["payload"]),
            claim_context=claim_context,
        )
    if tool_name == "gmail_update_draft":
        return gateway.update_gmail_draft(
            draft_id=cast(str, final_arguments["draft_id"]),
            payload=cast(dict[str, object], final_arguments["payload"]),
            claim_context=claim_context,
        )
    if tool_name == "tasks_create_task":
        return gateway.create_task(
            task_list_id=cast(str, final_arguments["task_list_id"]),
            payload=cast(dict[str, object], final_arguments["payload"]),
            claim_context=claim_context,
        )
    if tool_name == "tasks_update_task":
        return gateway.update_task(
            task_list_id=cast(str, final_arguments["task_list_id"]),
            task_id=cast(str, final_arguments["task_id"]),
            payload=cast(dict[str, object], final_arguments["payload"]),
            claim_context=claim_context,
        )
    if tool_name == "calendar_create_event":
        return gateway.create_calendar_event(
            calendar_id=cast(str, final_arguments["calendar_id"]),
            payload=cast(dict[str, object], final_arguments["payload"]),
            claim_context=claim_context,
        )
    if tool_name == "calendar_update_event":
        return gateway.update_calendar_event(
            calendar_id=cast(str, final_arguments["calendar_id"]),
            event_id=cast(str, final_arguments["event_id"]),
            payload=cast(dict[str, object], final_arguments["payload"]),
            claim_context=claim_context,
        )
    raise LookupError(f"unsupported write tool: {tool_name}")


def _prepare_gateway_claim_context(
    *,
    gateway: GoogleWorkspaceGateway,
    claim_payload: dict[str, object],
    tool_name: str,
    approval_arguments_hash: str,
    execution_arguments_hash: str,
) -> dict[str, object] | None:
    prepare = getattr(gateway, "prepare_claim_context", None)
    if not callable(prepare):
        return None
    return cast(
        dict[str, object],
        prepare(
            claim_payload=claim_payload,
            tool_name=tool_name,
            approval_arguments_hash=approval_arguments_hash,
            execution_arguments_hash=execution_arguments_hash,
        ),
    )


def _load_verification_snapshot(
    *,
    gateway: VerificationSnapshotGateway,
    action: ActionRecord,
    fallback_resource_id: str | None,
) -> ResourceSnapshot:
    arguments = loads(action.arguments_json)
    if action.tool_name in {"gmail_create_draft", "gmail_update_draft"}:
        draft_id = str(arguments.get("draft_id") or _required_resource_id(fallback_resource_id))
        return gateway.get_gmail_draft(draft_id=draft_id)
    if action.tool_name == "gmail_send":
        message_id = _required_resource_id(fallback_resource_id)
        return gateway.get_gmail_message(message_id=message_id)
    if action.tool_name in {"tasks_create_task", "tasks_update_task"}:
        task_list_id = str(arguments["task_list_id"])
        task_id = str(arguments.get("task_id") or _required_resource_id(fallback_resource_id))
        return gateway.get_task(task_list_id=task_list_id, task_id=task_id)
    if action.tool_name in {"calendar_create_event", "calendar_update_event"}:
        calendar_id = str(arguments["calendar_id"])
        event_id = str(arguments.get("event_id") or _required_resource_id(fallback_resource_id))
        return gateway.get_calendar_event(calendar_id=calendar_id, event_id=event_id)
    if action.tool_name == "calendar_delete_event":
        calendar_id = str(arguments["calendar_id"])
        event_id = str(arguments["event_id"])
        return gateway.get_calendar_event(calendar_id=calendar_id, event_id=event_id)
    if action.tool_name == "tasks_delete_task":
        task_list_id = str(arguments["task_list_id"])
        task_id = str(arguments["task_id"])
        return gateway.get_task(task_list_id=task_list_id, task_id=task_id)
    raise LookupError(f"unsupported verification tool: {action.tool_name}")


def _resolve_snapshot_fallback_resource_id(
    unit_of_work: UnitOfWork,
    *,
    action: ActionRecord,
    resource_ref_id: str | None,
) -> str | None:
    arguments = loads(action.arguments_json)
    if action.tool_name in {"gmail_create_draft", "gmail_update_draft"}:
        return (
            None
            if arguments.get("draft_id") is not None
            else _resource_id_from_ref(unit_of_work, resource_ref_id)
        )
    if action.tool_name in {"tasks_create_task", "tasks_update_task"}:
        return (
            None
            if arguments.get("task_id") is not None
            else _resource_id_from_ref(unit_of_work, resource_ref_id)
        )
    if action.tool_name in {"calendar_create_event", "calendar_update_event"}:
        return (
            None
            if arguments.get("event_id") is not None
            else _resource_id_from_ref(unit_of_work, resource_ref_id)
        )
    if action.tool_name == "gmail_send":
        return _resource_id_from_ref(unit_of_work, resource_ref_id)
    return None


def _required_resource_id(resource_id: str | None) -> str:
    if resource_id is None:
        raise LookupError("resource reference is required for verification")
    return resource_id


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
        ResourceType.GMAIL_MESSAGE: (ResourceSource.GMAIL, StoredResourceType.MESSAGE),
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


def _upsert_resource_ref(
    *, unit_of_work: UnitOfWork, resource_ref: ResourceRefRecord
) -> ResourceRefRecord:
    """Resolve the durable id because upsert may retain a pre-existing reference."""
    unit_of_work.resource_refs.upsert(resource_ref)
    persisted = unit_of_work.resource_refs.get_by_unique_key(
        run_id=resource_ref.run_id,
        source=resource_ref.source.value,
        resource_type=resource_ref.resource_type.value,
        resource_id=resource_ref.resource_id,
    )
    if persisted is None:
        raise RuntimeError("resource reference upsert did not persist")
    return persisted


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


def _write_action_version_conflict_response(
    *,
    action: ActionRecord,
    attempt_id: str,
    conflict_detail: str,
) -> WriteActionResponse:
    return WriteActionResponse(
        applied=False,
        result_code=ResultCode.VERSION_CONFLICT.value,
        action_id=action.id,
        action_status=action.status,
        action_version=action.version,
        next_allowed_commands=tuple(
            item.value for item in _next_allowed_write_commands_for_record(action)
        ),
        attempt_id=attempt_id,
        conflict_detail=conflict_detail,
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
    if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
        if receipt.request_hash != request_hash:
            return cast(
                WriteActionResponse,
                _resolve_json_receipt(
                    receipt=receipt,
                    request_hash=request_hash,
                    response_type=WriteActionResponse,
                ),
            )
        action = _require_action(unit_of_work, action_id)
        applied_statuses = {
            ActionStatus.FAILED.value,
            ActionStatus.UNKNOWN_RESULT.value,
            ActionStatus.EXECUTED.value,
            ActionStatus.VERIFIED.value,
            ActionStatus.MODIFIED.value,
            ActionStatus.MISMATCH.value,
            ActionStatus.DEPENDENCY_BLOCKED.value,
        }
        return WriteActionResponse(
            applied=action.status in applied_statuses,
            result_code=(
                ResultCode.TRANSITION_APPLIED.value
                if action.status in applied_statuses
                else ResultCode.RECOVERY_REQUIRED.value
            ),
            action_id=action.id,
            action_status=action.status,
            action_version=action.version,
            next_allowed_commands=tuple(
                item.value for item in _next_allowed_write_commands_for_record(action)
            ),
            conflict_detail=None
            if action.status in applied_statuses
            else "receipt exists in RECEIVED state; aggregate recovery is inconclusive",
        )
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
    | type[WriteActionResponse]
    | type[WriteRunResponse],
) -> SaveWritePlanResponse | PublishWritePlanResponse | WriteActionResponse | WriteRunResponse:
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
        if response_type is WriteRunResponse:
            return WriteRunResponse(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                run_id=receipt.aggregate_id or "",
                run_status="UNKNOWN",
                run_version=receipt.result_version or 0,
                plan_id=None,
                plan_status=None,
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
        raise RuntimeError("RECEIVED receipt recovery requires aggregate-specific handling")
    payload = loads(receipt.response_json)
    if "next_allowed_commands" in payload:
        payload["next_allowed_commands"] = tuple(payload["next_allowed_commands"])
    if "action_ids" in payload:
        payload["action_ids"] = tuple(payload["action_ids"])
    return response_type(**payload)


def _finish_json_receipt(
    unit_of_work: UnitOfWork,
    command_id: str,
    response: (
        SaveWritePlanResponse | PublishWritePlanResponse | WriteActionResponse | WriteRunResponse
    ),
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


def _require_latest_plan_for_run(unit_of_work: UnitOfWork, run_id: str) -> PlanRecord:
    plans = unit_of_work.plans.list_by_run(run_id)
    if not plans:
        raise LookupError(f"plan not found for run: {run_id}")
    return plans[-1]


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


def classify_write_delivery(error: GoogleWorkspaceGatewayError) -> DeliveryCertainty:
    return error.delivery_certainty


def _cancel_pending_actions(*, unit_of_work: UnitOfWork, plan_id: str, updated_at_ms: int) -> None:
    pending_statuses = {
        ActionStatus.PROPOSED.value,
        ActionStatus.MODIFIED.value,
        ActionStatus.APPROVED.value,
        ActionStatus.EXPIRED.value,
    }
    for action in unit_of_work.actions.list_by_plan(plan_id):
        if action.status not in pending_statuses:
            continue
        if action.status == ActionStatus.APPROVED.value:
            unit_of_work.approvals.revoke_active_by_action(action.id)
        result = unit_of_work.actions.cancel_pending(
            action.id,
            expected_version=action.version,
            updated_at_ms=updated_at_ms,
        )
        if not result.applied:
            raise RuntimeError(f"pending action cancellation failed: {action.id}")


def _has_successful_cancel_marker(unit_of_work: UnitOfWork, run_id: str) -> bool:
    cursor: int | None = None
    while True:
        events = unit_of_work.audits.list_by_aggregate(
            run_id=run_id,
            cursor_after=cursor,
            limit=100,
        )
        if any(
            event.event_type == "RUN_CANCELLATION_REQUESTED"
            and event.outcome == ResultCode.TRANSITION_APPLIED.value
            for event in events
        ):
            return True
        if len(events) < 100:
            return False
        cursor = events[-1].id


def _finish_recovery_response(
    *,
    unit_of_work: UnitOfWork,
    command_id: str,
    response: WriteRunResponse,
    now_ms: int,
) -> WriteRunResponse:
    _finish_json_receipt(
        unit_of_work,
        command_id,
        response,
        response.run_version,
        now_ms,
    )
    unit_of_work.commit()
    return response


def calculate_write_failure_result_code(error: GoogleWorkspaceGatewayError) -> ResultCode:
    return (
        ResultCode.RECOVERY_REQUIRED
        if classify_write_delivery(error) is not DeliveryCertainty.NOT_SENT
        else ResultCode.STATE_CONFLICT
    )


def is_reauth_required_error(error: GoogleWorkspaceGatewayError) -> bool:
    return error.code is GoogleWorkspaceErrorCode.AUTH_EXPIRED


def _dict_argument(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("expected a dict payload")
    return {str(key): cast(object, item) for key, item in value.items()}


def _calendar_conflict_audit_metadata(
    *, risk: dict[str, object], action_id: str
) -> dict[str, object]:
    authority = calendar_conflict_authority(risk) or ("UNKNOWN", ())
    value = risk.get("calendar_conflict")
    return {
        "action_id": action_id,
        "decision": authority[0],
        "matched_resource_ids": list(authority[1]),
        "reason_codes": value.get("reason_codes", []) if isinstance(value, dict) else [],
        "freshness": value.get("freshness", "UNKNOWN") if isinstance(value, dict) else "UNKNOWN",
    }


def _required_argument_string(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise PolicyViolationError(f"write action requires a non-empty {key}")
    return value


def _validate_preflight_target(
    *,
    snapshot: ResourceSnapshot,
    target_ref: ResourceRefRecord | None,
    expected_resource_type: ResourceType,
    expected_parent_id: str | None,
) -> None:
    if snapshot.resource_type is not expected_resource_type:
        raise PolicyViolationError("preflight target resource type mismatch")
    if expected_parent_id is not None and snapshot.parent_id != expected_parent_id:
        raise PolicyViolationError("preflight target parent mismatch")
    if target_ref is None:
        if expected_resource_type is ResourceType.CALENDAR_EVENT:
            raise PolicyViolationError("calendar delete requires a persisted target reference")
        if expected_resource_type is ResourceType.TASK:
            raise PolicyViolationError("task delete requires a persisted target reference")
        return
    if target_ref.resource_id != snapshot.resource_id:
        raise PolicyViolationError("preflight target identity mismatch")
    if target_ref.version_token is not None and target_ref.version_token != snapshot.version:
        raise PolicyViolationError("preflight target version mismatch")
    if (
        target_ref.parent_resource_id is not None
        and target_ref.parent_resource_id != snapshot.parent_id
    ):
        raise PolicyViolationError("preflight target parent reference mismatch")


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


def _propagate_dependency_blocked(
    *,
    unit_of_work: UnitOfWork,
    action_id: str,
    run_id: str,
    updated_at_ms: int,
) -> None:
    blocked_action_ids: list[str] = []
    for dependent_action_id in unit_of_work.action_dependencies.list_dependents(action_id):
        if unit_of_work.actions.mark_dependency_blocked(
            dependent_action_id,
            updated_at_ms=updated_at_ms,
        ):
            blocked_action_ids.append(dependent_action_id)
    for blocked_action_id in blocked_action_ids:
        unit_of_work.traces.add(
            TraceEventRecord(
                run_id=run_id,
                action_id=blocked_action_id,
                event_type="WRITE_DEPENDENCY_BLOCKED",
                status=ActionStatus.DEPENDENCY_BLOCKED.value,
                duration_ms=None,
                payload_json=dumps({"blocked_by_action_id": action_id}, sort_keys=True),
                created_at_ms=updated_at_ms,
            )
        )
        unit_of_work.audits.add(
            _audit_event(
                run_id=run_id,
                action_id=blocked_action_id,
                event_type="WRITE_DEPENDENCY_BLOCKED",
                outcome=ResultCode.TRANSITION_APPLIED.value,
                metadata={"blocked_by_action_id": action_id},
                created_at_ms=updated_at_ms,
            )
        )


def _recovery_resource_type_for_tool(tool_name: str) -> ResourceType:
    if tool_name == "gmail_send":
        return ResourceType.GMAIL_MESSAGE
    if tool_name.startswith("gmail_"):
        return ResourceType.GMAIL_DRAFT
    if tool_name.startswith("tasks_"):
        return ResourceType.TASK
    if tool_name.startswith("calendar_"):
        return ResourceType.CALENDAR_EVENT
    raise LookupError(f"unsupported recovery tool: {tool_name}")


def _resolve_existing_run_receipt(
    *,
    unit_of_work: UnitOfWork,
    receipt: CommandReceiptRecord,
    request_hash: str,
    run_id: str,
) -> WriteRunResponse:
    if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
        if receipt.request_hash != request_hash:
            return cast(
                WriteRunResponse,
                _resolve_json_receipt(
                    receipt=receipt,
                    request_hash=request_hash,
                    response_type=WriteRunResponse,
                ),
            )
        run = _require_run(unit_of_work, run_id)
        plans = unit_of_work.plans.list_by_run(run_id)
        plan = max(plans, key=lambda item: (item.revision_no, item.created_at_ms), default=None)
        applied_statuses = (
            {RunStatus.COMPLETED.value, RunStatus.PLANNING.value}
            if receipt.command_type == "ResolveMismatchRecovery"
            else {
                RunStatus.CANCEL_REQUESTED.value,
                RunStatus.CANCELLED.value,
                RunStatus.REAUTH_REQUIRED.value,
                RunStatus.RECOVERY_REQUIRED.value,
                RunStatus.VERIFYING.value,
            }
        )
        return WriteRunResponse(
            applied=run.status.value in applied_statuses,
            result_code=(
                ResultCode.TRANSITION_APPLIED.value
                if run.status.value in applied_statuses
                else ResultCode.RECOVERY_REQUIRED.value
            ),
            run_id=run.id,
            run_status=run.status.value,
            run_version=run.version,
            plan_id=None if plan is None else plan.id,
            plan_status=None if plan is None else plan.status.value,
            result_kind=run.status.value,
            conflict_detail=None
            if run.status.value in applied_statuses
            else "receipt exists in RECEIVED state; aggregate recovery is inconclusive",
        )
    return cast(
        WriteRunResponse,
        _resolve_json_receipt(
            receipt=receipt,
            request_hash=request_hash,
            response_type=WriteRunResponse,
        ),
    )


def _next_allowed_write_commands_for_record(action: ActionRecord) -> tuple[ActionCommand, ...]:
    return next_allowed_action_commands(
        ActionStatus(action.status),
        effect_type=EffectType(action.effect_type),
    )
