"""READ-only plan and action application flow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads

from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    CommandResult,
    EffectType,
    ResultCode,
    RunStatus,
    SignedToolRegistry,
    build_p0_tool_registry,
    calculate_canonical_json_hash,
    canonicalize_json_value,
    validate_evidence_policy,
)
from google_work_agent.ports import (
    ActionRecord,
    AuditEventRecord,
    CommandReceiptRecord,
    CommandReceiptStatus,
    EvidenceOriginType,
    EvidenceRecord,
    FreeBusyCalendar,
    GoogleWorkspaceGateway,
    PlanRecord,
    PlanStatus,
    ResourcePage,
    ResourceRefRecord,
    ResourceSnapshot,
    ResourceSource,
    RunRecord,
    StoredResourceType,
    TimeRange,
    TraceEventRecord,
    UnitOfWork,
)

READ_ACTION_TERMINAL_STATUSES = frozenset(
    {
        ActionStatus.VERIFIED,
        ActionStatus.FAILED,
        ActionStatus.BLOCKED,
        ActionStatus.DEPENDENCY_BLOCKED,
        ActionStatus.REJECTED,
        ActionStatus.EXPIRED,
        ActionStatus.MISMATCH,
    }
)


@dataclass(frozen=True, slots=True)
class _PendingReceiptResolution[T]:
    should_return: bool
    response: T | None = None


DEPENDENCY_FAILURE_STATUSES = frozenset(
    {
        ActionStatus.FAILED,
        ActionStatus.BLOCKED,
        ActionStatus.DEPENDENCY_BLOCKED,
        ActionStatus.REJECTED,
        ActionStatus.EXPIRED,
        ActionStatus.MISMATCH,
    }
)


@dataclass(frozen=True, slots=True)
class ReadEvidenceDraft:
    """Input evidence row for a read-only plan draft."""

    evidence_id: str
    origin_type: EvidenceOriginType
    kind: str
    excerpt: str
    locator_json: str | None = None
    resource_ref_id: str | None = None
    message_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReadActionDraft:
    """Input action row for a read-only plan draft."""

    action_id: str
    position: int
    tool_name: str
    arguments: dict[str, object]
    expected: dict[str, object]
    evidence_ids: tuple[str, ...]
    depends_on_action_ids: tuple[str, ...] = ()
    target_resource_ref_id: str | None = None


@dataclass(frozen=True, slots=True)
class SaveReadOnlyPlanCommand:
    """Save one explicit read-only plan draft."""

    command_id: str
    request_hash: str
    plan_id: str
    run_id: str
    revision_no: int
    summary_text: str
    expected_run_version: int
    actions: tuple[ReadActionDraft, ...]
    evidence: tuple[ReadEvidenceDraft, ...]


@dataclass(frozen=True, slots=True)
class PublishReadOnlyPlanCommand:
    """Publish one read-only plan."""

    command_id: str
    request_hash: str
    plan_id: str
    run_id: str
    expected_run_version: int


@dataclass(frozen=True, slots=True)
class ClaimReadActionCommand:
    """Claim one read action."""

    command_id: str
    request_hash: str
    action_id: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class CompletedResourceRef:
    """Projected resource reference from a read result."""

    id: str
    source: ResourceSource
    resource_type: StoredResourceType
    resource_id: str
    parent_resource_id: str | None
    canonical_url: str | None
    title: str | None
    event_time_ms: int | None
    version_token: str | None
    metadata_json: str


@dataclass(frozen=True, slots=True)
class CompletedEvidence:
    """Projected evidence row from a read result."""

    id: str
    origin_type: EvidenceOriginType
    kind: str
    excerpt: str
    locator_json: str | None
    resource_ref_id: str | None = None
    message_id: str | None = None


@dataclass(frozen=True, slots=True)
class CompleteReadActionCommand:
    """Persist a successful read action result."""

    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    output_json: str
    resource_refs: tuple[CompletedResourceRef, ...]
    evidence: tuple[CompletedEvidence, ...]


@dataclass(frozen=True, slots=True)
class FinalizeReadActionCommand:
    """Finalize an executed read action."""

    command_id: str
    request_hash: str
    action_id: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class FailReadActionCommand:
    """Persist a failed read action result."""

    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    safe_error_code: str
    retryable: bool
    safe_error_detail: str


@dataclass(frozen=True, slots=True)
class SaveReadOnlyPlanResponse:
    """Result of saving a read-only plan."""

    applied: bool
    result_code: str
    run_status: str
    run_version: int
    plan_id: str
    plan_status: str
    action_ids: tuple[str, ...]
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class PublishReadOnlyPlanResponse:
    """Result of publishing a read-only plan."""

    applied: bool
    result_code: str
    run_status: str
    run_version: int
    plan_id: str
    plan_status: str
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class ReadActionCommandResponse:
    """Result of a read action command."""

    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    plan_completed: bool = False
    run_completed: bool = False
    partial: bool = False
    safe_error_code: str | None = None
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutedReadAction:
    """Typed output from one dispatched read action."""

    output_json: str
    resource_refs: tuple[CompletedResourceRef, ...]
    evidence: tuple[CompletedEvidence, ...]


type ReadOnlyResponse = (
    SaveReadOnlyPlanResponse | PublishReadOnlyPlanResponse | ReadActionCommandResponse
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
                resolution = _handle_existing_save_receipt(
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

            run = _require_run(unit_of_work, command.run_id)
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
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run.version, now_ms
                )
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
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run.version, now_ms
                )
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
                _audit_event(
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
            _finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
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
                resolution = _handle_existing_publish_receipt(
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

            plan = _require_plan(unit_of_work, command.plan_id)
            run = _require_run(unit_of_work, command.run_id)
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
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run.version, now_ms
                )
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
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run.version, now_ms
                )
                unit_of_work.commit()
                return response
            _validate_published_actions_are_read(actions)

            run_result = unit_of_work.runs.publish_read_only_plan(
                command.run_id,
                expected_version=command.expected_run_version,
            )
            if not run_result.applied:
                response = PublishReadOnlyPlanResponse(
                    applied=False,
                    result_code=run_result.result_code.value,
                    run_status=run_result.current_status.value,
                    run_version=run_result.current_version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail=run_result.conflict_detail,
                )
                _finish_json_receipt(
                    unit_of_work,
                    command.command_id,
                    response,
                    run_result.current_version,
                    now_ms,
                )
                unit_of_work.commit()
                return response

            unit_of_work.plans.activate(plan.id)
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
                _audit_event(
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
                result_code=run_result.result_code.value,
                run_status=run_result.current_status.value,
                run_version=run_result.current_version,
                plan_id=plan.id,
                plan_status=PlanStatus.ACTIVE.value,
            )
            _finish_json_receipt(
                unit_of_work,
                command.command_id,
                response,
                run_result.current_version,
                now_ms,
            )
            unit_of_work.commit()
            return response


class ClaimReadActionService:
    """Claim one read action without invoking the external gateway in-transaction."""

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: ClaimReadActionCommand) -> ReadActionCommandResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing_receipt = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing_receipt is not None:
                resolution = _handle_existing_claim_receipt(
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
                        raise RuntimeError("claim receipt recovery produced no response")
                    return resolution.response

            now_ms = self._now_ms()
            if existing_receipt is None:
                unit_of_work.command_receipts.add_received(
                    command_id=command.command_id,
                    command_type="ClaimReadAction",
                    request_hash=command.request_hash,
                    aggregate_type="Action",
                    aggregate_id=command.action_id,
                    created_at_ms=now_ms,
                )

            action = _require_action(unit_of_work, command.action_id)
            if ActionStatus(action.status) in READ_ACTION_TERMINAL_STATUSES:
                response = _action_conflict_response(
                    action=action,
                    result_code=ResultCode.STATE_CONFLICT,
                    conflict_detail="terminal action cannot be claimed again",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response
            if len(unit_of_work.action_dependencies.list_dependencies(action.id)) > 0:
                ready_ids = {
                    item.id for item in unit_of_work.actions.list_ready_actions(action.plan_id)
                }
                if action.id not in ready_ids:
                    response = _action_conflict_response(
                        action=action,
                        result_code=ResultCode.STATE_CONFLICT,
                        conflict_detail="dependencies are not yet satisfied",
                    )
                    _finish_json_receipt(
                        unit_of_work, command.command_id, response, action.version, now_ms
                    )
                    unit_of_work.commit()
                    return response

            result = unit_of_work.actions.claim_read(
                command.action_id,
                expected_version=command.expected_version,
                updated_at_ms=now_ms,
            )
            response = _action_result_response(command.action_id, result)
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=_require_plan(unit_of_work, action.plan_id).run_id,
                    action_id=command.action_id,
                    event_type="READ_ACTION_CLAIMED",
                    status=response.action_status,
                    duration_ms=None,
                    payload_json=dumps({"command_id": command.command_id}, sort_keys=True),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=_require_plan(unit_of_work, action.plan_id).run_id,
                    action_id=command.action_id,
                    event_type="COMMAND_APPLIED" if response.applied else "COMMAND_REJECTED",
                    outcome=response.result_code,
                    metadata={"command_id": command.command_id},
                    created_at_ms=now_ms,
                )
            )
            _finish_json_receipt(
                unit_of_work, command.command_id, response, response.action_version, now_ms
            )
            unit_of_work.commit()
            return response


class CompleteReadActionService:
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
                resolution = _handle_existing_complete_receipt(
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

            action = _require_action(unit_of_work, command.action_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            if len(command.resource_refs) == 0 and len(command.evidence) == 0:
                raise ValueError(
                    "read completion requires at least one projected resource or evidence"
                )
            if action.version != command.expected_version:
                response = _action_conflict_response(
                    action=action,
                    result_code=ResultCode.VERSION_CONFLICT,
                    conflict_detail="expected_version does not match current_version",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response
            if ActionStatus(action.status) is not ActionStatus.EXECUTING:
                response = _action_conflict_response(
                    action=action,
                    result_code=ResultCode.STATE_CONFLICT,
                    conflict_detail="complete_read_action requires EXECUTING status",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response

            for resource_ref in command.resource_refs:
                unit_of_work.resource_refs.upsert(
                    ResourceRefRecord(
                        id=resource_ref.id,
                        run_id=plan.run_id,
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

            result = unit_of_work.actions.complete_read(
                command.action_id,
                expected_version=command.expected_version,
                updated_at_ms=now_ms,
            )
            response = _action_result_response(command.action_id, result)
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
                _audit_event(
                    run_id=plan.run_id,
                    action_id=command.action_id,
                    event_type="COMMAND_APPLIED" if response.applied else "COMMAND_REJECTED",
                    outcome=response.result_code,
                    metadata={
                        "command_id": command.command_id,
                        "resource_ref_count": len(command.resource_refs),
                        "evidence_count": len(command.evidence),
                    },
                    created_at_ms=now_ms,
                )
            )
            _finish_json_receipt(
                unit_of_work, command.command_id, response, response.action_version, now_ms
            )
            unit_of_work.commit()
            return response


class FinalizeReadActionService:
    """Finalize one executed read action and reconcile parent state."""

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: FinalizeReadActionCommand) -> ReadActionCommandResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing_receipt = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing_receipt is not None:
                resolution = _handle_existing_finalize_receipt(
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
                        raise RuntimeError("finalize receipt recovery produced no response")
                    return resolution.response

            now_ms = self._now_ms()
            if existing_receipt is None:
                unit_of_work.command_receipts.add_received(
                    command_id=command.command_id,
                    command_type="FinalizeReadAction",
                    request_hash=command.request_hash,
                    aggregate_type="Action",
                    aggregate_id=command.action_id,
                    created_at_ms=now_ms,
                )

            action = _require_action(unit_of_work, command.action_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            result = unit_of_work.actions.finalize_read(
                command.action_id,
                expected_version=command.expected_version,
                updated_at_ms=now_ms,
            )
            response = _action_result_response(command.action_id, result)
            aggregate = _reconcile_read_plan_state(unit_of_work, plan.id, now_ms)
            response = ReadActionCommandResponse(
                **{
                    **asdict(response),
                    "plan_completed": aggregate.plan_completed,
                    "run_completed": aggregate.run_completed,
                    "partial": aggregate.partial,
                }
            )
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=command.action_id,
                    event_type="READ_ACTION_FINALIZED",
                    status=response.action_status,
                    duration_ms=None,
                    payload_json=dumps(
                        {"command_id": command.command_id, "partial": aggregate.partial},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=command.action_id,
                    event_type="COMMAND_APPLIED" if response.applied else "COMMAND_REJECTED",
                    outcome=response.result_code,
                    metadata={"command_id": command.command_id, "partial": aggregate.partial},
                    created_at_ms=now_ms,
                )
            )
            _finish_json_receipt(
                unit_of_work, command.command_id, response, response.action_version, now_ms
            )
            unit_of_work.commit()
            return response


class FailReadActionService:
    """Mark one executing read action as failed and reconcile dependencies."""

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: FailReadActionCommand) -> ReadActionCommandResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing_receipt = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing_receipt is not None:
                resolution = _handle_existing_fail_receipt(
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
                        raise RuntimeError("fail receipt recovery produced no response")
                    return resolution.response

            now_ms = self._now_ms()
            if existing_receipt is None:
                unit_of_work.command_receipts.add_received(
                    command_id=command.command_id,
                    command_type="FailReadAction",
                    request_hash=command.request_hash,
                    aggregate_type="Action",
                    aggregate_id=command.action_id,
                    created_at_ms=now_ms,
                )

            action = _require_action(unit_of_work, command.action_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            result = unit_of_work.actions.fail_read(
                command.action_id,
                expected_version=command.expected_version,
                updated_at_ms=now_ms,
            )
            response = _action_result_response(command.action_id, result)
            aggregate = _reconcile_read_plan_state(unit_of_work, plan.id, now_ms)
            response = ReadActionCommandResponse(
                **{
                    **asdict(response),
                    "plan_completed": aggregate.plan_completed,
                    "run_completed": aggregate.run_completed,
                    "partial": aggregate.partial,
                    "safe_error_code": command.safe_error_code,
                }
            )
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=command.action_id,
                    event_type="READ_ACTION_FAILED",
                    status=response.action_status,
                    duration_ms=None,
                    payload_json=dumps(
                        {
                            "command_id": command.command_id,
                            "safe_error_code": command.safe_error_code,
                            "retryable": command.retryable,
                            "detail": command.safe_error_detail,
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=command.action_id,
                    event_type="COMMAND_APPLIED" if response.applied else "COMMAND_REJECTED",
                    outcome=response.result_code,
                    metadata={
                        "command_id": command.command_id,
                        "safe_error_code": command.safe_error_code,
                    },
                    created_at_ms=now_ms,
                )
            )
            _finish_json_receipt(
                unit_of_work, command.command_id, response, response.action_version, now_ms
            )
            unit_of_work.commit()
            return response


class ExecuteReadActionService:
    """Execute one claimed read action outside of any SQLite transaction."""

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], gateway: GoogleWorkspaceGateway
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._gateway = gateway
        self._dispatch = {
            "gmail_search_threads": self._execute_gmail_search_threads,
            "gmail_get_thread": self._execute_get_gmail_thread,
            "gmail_get_message": self._execute_get_gmail_message,
            "tasks_list_tasklists": self._execute_list_task_lists,
            "tasks_list_tasks": self._execute_list_tasks,
            "tasks_get_task": self._execute_get_task,
            "calendar_list_calendars": self._execute_list_calendars,
            "calendar_list_events": self._execute_list_calendar_events,
            "calendar_query_freebusy": self._execute_query_freebusy,
            "calendar_get_event": self._execute_get_calendar_event,
        }

    def __call__(self, *, action_id: str) -> ExecutedReadAction:
        with self._unit_of_work_factory() as unit_of_work:
            action = _require_action(unit_of_work, action_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            run = _require_run(unit_of_work, plan.run_id)
        if ActionStatus(action.status) is not ActionStatus.EXECUTING:
            raise RuntimeError(f"read action must be EXECUTING before external call: {action_id}")
        dispatch = self._dispatch.get(action.tool_name)
        if dispatch is None:
            raise RuntimeError(f"unsupported read tool dispatch: {action.tool_name}")
        return dispatch(run_id=run.id, arguments=loads(action.arguments_json))

    def _execute_gmail_search_threads(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        result = self._gateway.search_gmail_threads(
            query=str(arguments.get("query", "")),
            page_token=_optional_str(arguments.get("page_token")),
            page_size=_int_argument(arguments.get("page_size"), default=50),
        )
        return _executed_from_resource_page(run_id=run_id, page=result)

    def _execute_get_gmail_thread(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        result = self._gateway.get_gmail_thread(thread_id=str(arguments["thread_id"]))
        return _executed_from_snapshot(run_id=run_id, snapshot=result)

    def _execute_get_gmail_message(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        result = self._gateway.get_gmail_message(message_id=str(arguments["message_id"]))
        return _executed_from_snapshot(run_id=run_id, snapshot=result)

    def _execute_list_task_lists(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        result = self._gateway.list_task_lists(
            page_token=_optional_str(arguments.get("page_token")),
            page_size=_int_argument(arguments.get("page_size"), default=50),
        )
        return _executed_from_resource_page(run_id=run_id, page=result)

    def _execute_list_tasks(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        result = self._gateway.list_tasks(
            task_list_id=str(arguments["task_list_id"]),
            page_token=_optional_str(arguments.get("page_token")),
            page_size=_int_argument(arguments.get("page_size"), default=50),
        )
        return _executed_from_resource_page(run_id=run_id, page=result)

    def _execute_get_task(self, *, run_id: str, arguments: dict[str, object]) -> ExecutedReadAction:
        result = self._gateway.get_task(
            task_list_id=str(arguments["task_list_id"]),
            task_id=str(arguments["task_id"]),
        )
        return _executed_from_snapshot(run_id=run_id, snapshot=result)

    def _execute_list_calendars(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        result = self._gateway.list_calendars(
            page_token=_optional_str(arguments.get("page_token")),
            page_size=_int_argument(arguments.get("page_size"), default=50),
        )
        return _executed_from_resource_page(run_id=run_id, page=result)

    def _execute_list_calendar_events(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        result = self._gateway.list_calendar_events(
            calendar_id=str(arguments["calendar_id"]),
            page_token=_optional_str(arguments.get("page_token")),
            page_size=_int_argument(arguments.get("page_size"), default=50),
        )
        return _executed_from_resource_page(run_id=run_id, page=result)

    def _execute_query_freebusy(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        calendar_ids = _string_tuple_argument(arguments.get("calendar_ids"))
        time_range = TimeRange(
            start=str(arguments["time_min"]),
            end=str(arguments["time_max"]),
        )
        result = self._gateway.query_freebusy(
            calendar_ids=calendar_ids,
            time_range=time_range,
        )
        return _executed_from_freebusy(run_id=run_id, calendars=result)

    def _execute_get_calendar_event(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        result = self._gateway.get_calendar_event(
            calendar_id=str(arguments["calendar_id"]),
            event_id=str(arguments["event_id"]),
        )
        return _executed_from_snapshot(run_id=run_id, snapshot=result)


@dataclass(frozen=True, slots=True)
class _AggregateState:
    plan_completed: bool
    run_completed: bool
    partial: bool


def _validate_read_only_plan(
    command: SaveReadOnlyPlanCommand,
    registry: SignedToolRegistry,
) -> None:
    if len(command.actions) == 0:
        raise ValueError("read-only plan requires at least one action")
    action_ids = {item.action_id for item in command.actions}
    if len(action_ids) != len(command.actions):
        raise ValueError("duplicate action_id in read-only plan")
    positions = {item.position for item in command.actions}
    if len(positions) != len(command.actions):
        raise ValueError("duplicate action position in read-only plan")
    evidence_ids = {item.evidence_id for item in command.evidence}
    if len(evidence_ids) != len(command.evidence):
        raise ValueError("duplicate evidence_id in read-only plan")

    adjacency: dict[str, tuple[str, ...]] = {}
    for action in command.actions:
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
        for evidence_id in action.evidence_ids:
            if evidence_id not in evidence_ids:
                raise LookupError(f"action references missing evidence: {evidence_id}")
        for depends_on_action_id in action.depends_on_action_ids:
            if depends_on_action_id == action.action_id:
                raise ValueError("action cannot depend on itself")
            if depends_on_action_id not in action_ids:
                raise LookupError(f"action dependency not found: {depends_on_action_id}")
        adjacency[action.action_id] = action.depends_on_action_ids
    _validate_no_dependency_cycle(adjacency)


def _validate_no_dependency_cycle(adjacency: dict[str, tuple[str, ...]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def _visit(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            raise ValueError("action dependency cycle detected")
        visiting.add(node)
        for dependency in adjacency[node]:
            _visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in adjacency:
        _visit(node)


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


def _action_result_response(
    action_id: str,
    result: CommandResult[ActionStatus, ActionCommand],
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


def _action_conflict_response(
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


def _serialize_response(response: ReadOnlyResponse) -> str:
    return dumps(asdict(response), sort_keys=True)


def _finish_json_receipt(
    unit_of_work: UnitOfWork,
    command_id: str,
    response: ReadOnlyResponse,
    result_version: int,
    completed_at_ms: int,
) -> None:
    applied = bool(response.applied)
    result_code = ResultCode(str(response.result_code))
    unit_of_work.command_receipts.finish_json(
        command_id=command_id,
        applied=applied,
        result_code=result_code,
        result_version=result_version,
        response_json=_serialize_response(response),
        completed_at_ms=completed_at_ms,
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


def _handle_existing_save_receipt(
    *,
    unit_of_work: UnitOfWork,
    command: SaveReadOnlyPlanCommand,
    request_hash: str,
    run_id: str,
    receipt: CommandReceiptRecord,
    completed_at_ms: int,
) -> _PendingReceiptResolution[SaveReadOnlyPlanResponse]:
    if receipt.request_hash != request_hash:
        run = _require_run(unit_of_work, run_id)
        return _PendingReceiptResolution(
            should_return=True,
            response=SaveReadOnlyPlanResponse(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                run_status=run.status.value,
                run_version=run.version,
                plan_id="",
                plan_status=PlanStatus.DRAFT.value,
                action_ids=(),
                conflict_detail="command_id already exists with a different request_hash",
            ),
        )
    if receipt.response_json is not None and receipt.status is not CommandReceiptStatus.RECEIVED:
        return _PendingReceiptResolution(
            should_return=True,
            response=_deserialize_save_plan_response(receipt.response_json),
        )

    run = _require_run(unit_of_work, run_id)
    plan = unit_of_work.plans.get_by_id(command.plan_id)
    if plan is None:
        if run.status is RunStatus.PLANNING and run.version == command.expected_run_version:
            return _PendingReceiptResolution(should_return=False)
        response = _recovery_required_save_response(
            run=run,
            command=command,
            conflict_detail="save_read_only_plan receipt recovery is ambiguous",
        )
        _finish_json_receipt(
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
        _finish_json_receipt(
            unit_of_work, command.command_id, response, run.version, completed_at_ms
        )
        unit_of_work.commit()
        return _PendingReceiptResolution(should_return=True, response=response)

    response = _recovery_required_save_response(
        run=run,
        command=command,
        conflict_detail="save_read_only_plan detected partial persisted rows",
    )
    _finish_json_receipt(unit_of_work, command.command_id, response, run.version, completed_at_ms)
    unit_of_work.commit()
    return _PendingReceiptResolution(should_return=True, response=response)


def _handle_existing_publish_receipt(
    *,
    unit_of_work: UnitOfWork,
    command: PublishReadOnlyPlanCommand,
    request_hash: str,
    run_id: str,
    receipt: CommandReceiptRecord,
    completed_at_ms: int,
) -> _PendingReceiptResolution[PublishReadOnlyPlanResponse]:
    if receipt.request_hash != request_hash:
        run = _require_run(unit_of_work, run_id)
        return _PendingReceiptResolution(
            should_return=True,
            response=PublishReadOnlyPlanResponse(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                run_status=run.status.value,
                run_version=run.version,
                plan_id="",
                plan_status=PlanStatus.DRAFT.value,
                conflict_detail="command_id already exists with a different request_hash",
            ),
        )
    if receipt.response_json is not None and receipt.status is not CommandReceiptStatus.RECEIVED:
        return _PendingReceiptResolution(
            should_return=True,
            response=_deserialize_publish_plan_response(receipt.response_json),
        )

    run = _require_run(unit_of_work, run_id)
    plan = _require_plan(unit_of_work, command.plan_id)
    if plan.status in {PlanStatus.ACTIVE, PlanStatus.COMPLETED} and run.status in {
        RunStatus.EXECUTING,
        RunStatus.COMPLETED,
    }:
        response = PublishReadOnlyPlanResponse(
            applied=True,
            result_code=ResultCode.TRANSITION_APPLIED.value,
            run_status=run.status.value,
            run_version=run.version,
            plan_id=plan.id,
            plan_status=plan.status.value,
        )
        _finish_json_receipt(
            unit_of_work, command.command_id, response, run.version, completed_at_ms
        )
        unit_of_work.commit()
        return _PendingReceiptResolution(should_return=True, response=response)
    if (
        plan.status is PlanStatus.DRAFT
        and run.status is RunStatus.PLANNING
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
    _finish_json_receipt(unit_of_work, command.command_id, response, run.version, completed_at_ms)
    unit_of_work.commit()
    return _PendingReceiptResolution(should_return=True, response=response)


def _handle_existing_claim_receipt(
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
        action = _require_action(unit_of_work, action_id)
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

    action = _require_action(unit_of_work, action_id)
    if (
        action.status != ActionStatus.PROPOSED.value
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
        _finish_json_receipt(unit_of_work, command_id, response, action.version, completed_at_ms)
        unit_of_work.commit()
        return _PendingReceiptResolution(should_return=True, response=response)
    if action.status == ActionStatus.PROPOSED.value and action.version == command.expected_version:
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
    _finish_json_receipt(unit_of_work, command_id, response, action.version, completed_at_ms)
    unit_of_work.commit()
    return _PendingReceiptResolution(should_return=True, response=response)


def _handle_existing_complete_receipt(
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

    action = _require_action(unit_of_work, action_id)
    plan = _require_plan(unit_of_work, action.plan_id)
    if action.status in {ActionStatus.EXECUTED.value, ActionStatus.VERIFIED.value}:
        if _complete_projection_matches(
            unit_of_work=unit_of_work, run_id=plan.run_id, command=command
        ):
            response = ReadActionCommandResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                action_id=action.id,
                action_status=action.status,
                action_version=action.version,
                next_allowed_commands=(),
            )
            _finish_json_receipt(
                unit_of_work, command_id, response, action.version, completed_at_ms
            )
            unit_of_work.commit()
            return _PendingReceiptResolution(should_return=True, response=response)
        return _return_recovery_required_action(
            unit_of_work=unit_of_work,
            command_id=command_id,
            action=action,
            completed_at_ms=completed_at_ms,
            detail="complete_read_action detected partial projection persistence",
        )
    if action.status == ActionStatus.EXECUTING.value and action.version == command.expected_version:
        if _complete_projection_matches(
            unit_of_work=unit_of_work, run_id=plan.run_id, command=command
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


def _handle_existing_finalize_receipt(
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

    action = _require_action(unit_of_work, action_id)
    plan = _require_plan(unit_of_work, action.plan_id)
    if action.status == ActionStatus.VERIFIED.value:
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
            _finish_json_receipt(
                unit_of_work, command_id, response, action.version, completed_at_ms
            )
            unit_of_work.commit()
            return _PendingReceiptResolution(should_return=True, response=response)
        return _return_recovery_required_action(
            unit_of_work=unit_of_work,
            command_id=command_id,
            action=action,
            completed_at_ms=completed_at_ms,
            detail="finalize_read_action parent reconciliation is incomplete",
        )
    if action.status == ActionStatus.EXECUTED.value and action.version == command.expected_version:
        return _PendingReceiptResolution(should_return=False)
    return _return_recovery_required_action(
        unit_of_work=unit_of_work,
        command_id=command_id,
        action=action,
        completed_at_ms=completed_at_ms,
        detail="finalize_read_action receipt recovery is ambiguous",
    )


def _handle_existing_fail_receipt(
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

    action = _require_action(unit_of_work, action_id)
    plan = _require_plan(unit_of_work, action.plan_id)
    if action.status == ActionStatus.FAILED.value:
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
            _finish_json_receipt(
                unit_of_work, command_id, response, action.version, completed_at_ms
            )
            unit_of_work.commit()
            return _PendingReceiptResolution(should_return=True, response=response)
        return _return_recovery_required_action(
            unit_of_work=unit_of_work,
            command_id=command_id,
            action=action,
            completed_at_ms=completed_at_ms,
            detail="fail_read_action parent reconciliation is incomplete",
        )
    if action.status == ActionStatus.EXECUTING.value and action.version == command.expected_version:
        return _PendingReceiptResolution(should_return=False)
    return _return_recovery_required_action(
        unit_of_work=unit_of_work,
        command_id=command_id,
        action=action,
        completed_at_ms=completed_at_ms,
        detail="fail_read_action receipt recovery is ambiguous",
    )


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
        action = _require_action(unit_of_work, action_id)
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
    persisted_actions = unit_of_work.actions.list_by_plan(plan.id)
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
        if tuple(unit_of_work.action_dependencies.list_dependencies(action.id)) != tuple(
            sorted(draft.depends_on_action_ids)
        ):
            return False
        linked_evidence = {item.id for item in unit_of_work.evidence.list_by_action(action.id)}
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
            for item in unit_of_work.evidence.list_by_action(action.id)
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
        plan_status=PlanStatus.DRAFT.value,
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
    _finish_json_receipt(unit_of_work, command_id, response, action.version, completed_at_ms)
    unit_of_work.commit()
    return _PendingReceiptResolution(should_return=True, response=response)


def _complete_projection_matches(
    *,
    unit_of_work: UnitOfWork,
    run_id: str,
    command: CompleteReadActionCommand,
) -> bool:
    for resource_ref in command.resource_refs:
        persisted_ref = unit_of_work.resource_refs.get_by_unique_key(
            run_id=run_id,
            source=resource_ref.source.value,
            resource_type=resource_ref.resource_type.value,
            resource_id=resource_ref.resource_id,
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
        item.id: item for item in unit_of_work.evidence.list_by_action(command.action_id)
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
    actions = unit_of_work.actions.list_by_plan(plan_id)
    dependencies = {
        action.id: unit_of_work.action_dependencies.list_dependencies(action.id)
        for action in actions
    }
    action_statuses = {action.id: ActionStatus(action.status) for action in actions}
    if any(
        action_statuses[action.id] is ActionStatus.PROPOSED
        and dependencies[action.id]
        and any(
            action_statuses[dep] in DEPENDENCY_FAILURE_STATUSES for dep in dependencies[action.id]
        )
        for action in actions
    ):
        return _AggregateState(plan_completed=False, run_completed=False, partial=True)

    statuses = [ActionStatus(action.status) for action in actions]
    partial = any(status is not ActionStatus.VERIFIED for status in statuses)
    if any(status not in READ_ACTION_TERMINAL_STATUSES for status in statuses):
        return _AggregateState(plan_completed=False, run_completed=False, partial=partial)
    return _AggregateState(plan_completed=True, run_completed=True, partial=partial)


def _plan_and_run_match_reconciled_state(
    unit_of_work: UnitOfWork,
    plan: PlanRecord,
    aggregate: _AggregateState,
) -> bool:
    run = _require_run(unit_of_work, plan.run_id)
    expected_plan_status = PlanStatus.COMPLETED if aggregate.plan_completed else PlanStatus.ACTIVE
    expected_run_status = RunStatus.COMPLETED if aggregate.run_completed else RunStatus.EXECUTING
    return plan.status is expected_plan_status and run.status is expected_run_status


def _reconcile_read_plan_state(
    unit_of_work: UnitOfWork,
    plan_id: str,
    now_ms: int,
) -> _AggregateState:
    while True:
        actions = unit_of_work.actions.list_by_plan(plan_id)
        dependencies = {
            action.id: unit_of_work.action_dependencies.list_dependencies(action.id)
            for action in actions
        }
        action_statuses = {action.id: ActionStatus(action.status) for action in actions}
        changed = False
        for action in actions:
            if ActionStatus(action.status) is not ActionStatus.PROPOSED:
                continue
            deps = dependencies[action.id]
            if deps and any(action_statuses[dep] in DEPENDENCY_FAILURE_STATUSES for dep in deps):
                changed = (
                    unit_of_work.actions.mark_dependency_blocked(
                        action.id,
                        updated_at_ms=now_ms,
                    )
                    or changed
                )
        if not changed:
            break

    actions = unit_of_work.actions.list_by_plan(plan_id)
    terminal_statuses = [ActionStatus(action.status) for action in actions]
    partial = any(status is not ActionStatus.VERIFIED for status in terminal_statuses)
    if any(status not in READ_ACTION_TERMINAL_STATUSES for status in terminal_statuses):
        return _AggregateState(plan_completed=False, run_completed=False, partial=partial)

    plan = _require_plan(unit_of_work, plan_id)
    run = _require_run(unit_of_work, plan.run_id)
    if plan.status is PlanStatus.ACTIVE:
        unit_of_work.plans.complete(plan.id)
    run_result = unit_of_work.runs.complete_read_only_run(
        run.id,
        expected_version=run.version,
        finished_at_ms=now_ms,
    )
    return _AggregateState(
        plan_completed=True,
        run_completed=run_result.applied,
        partial=partial,
    )


def _executed_from_resource_page(run_id: str, page: ResourcePage) -> ExecutedReadAction:
    resources: list[CompletedResourceRef] = []
    evidence: list[CompletedEvidence] = []
    for snapshot in page.items:
        resource_ref, evidence_row = _projection_from_snapshot(run_id=run_id, snapshot=snapshot)
        resources.append(resource_ref)
        evidence.append(evidence_row)
    return ExecutedReadAction(
        output_json=dumps(
            {
                "result_kind": "RESOURCE_PAGE",
                "resource_ids": [item.resource_id for item in page.items],
                "next_page_token": page.next_page_token,
            },
            sort_keys=True,
        ),
        resource_refs=tuple(resources),
        evidence=tuple(evidence),
    )


def _executed_from_snapshot(run_id: str, snapshot: ResourceSnapshot) -> ExecutedReadAction:
    resource_ref, evidence = _projection_from_snapshot(run_id=run_id, snapshot=snapshot)
    return ExecutedReadAction(
        output_json=dumps(
            {"result_kind": "RESOURCE", "resource_id": snapshot.resource_id},
            sort_keys=True,
        ),
        resource_refs=(resource_ref,),
        evidence=(evidence,),
    )


def _executed_from_freebusy(
    run_id: str,
    calendars: tuple[FreeBusyCalendar, ...],
) -> ExecutedReadAction:
    resources: list[CompletedResourceRef] = []
    evidence: list[CompletedEvidence] = []
    for calendar in calendars:
        calendar_id = str(calendar.calendar_id)
        resources.append(
            CompletedResourceRef(
                id=f"resource-ref-{run_id}-{calendar_id}",
                source=ResourceSource.CALENDAR,
                resource_type=StoredResourceType.CALENDAR,
                resource_id=calendar_id,
                parent_resource_id=None,
                canonical_url=None,
                title=f"Calendar {calendar_id}",
                event_time_ms=None,
                version_token=None,
                metadata_json=dumps({"interval_count": len(calendar.intervals)}, sort_keys=True),
            )
        )
        evidence.append(
            CompletedEvidence(
                id=f"evidence-{run_id}-{calendar_id}",
                origin_type=EvidenceOriginType.DERIVED,
                kind="FREEBUSY",
                excerpt=f"Calendar {calendar_id} busy intervals: {len(calendar.intervals)}",
                locator_json=None,
            )
        )
    return ExecutedReadAction(
        output_json=dumps(
            {
                "result_kind": "FREEBUSY",
                "calendar_ids": [str(calendar.calendar_id) for calendar in calendars],
            },
            sort_keys=True,
        ),
        resource_refs=tuple(resources),
        evidence=tuple(evidence),
    )


def _projection_from_snapshot(
    *,
    run_id: str,
    snapshot: ResourceSnapshot,
) -> tuple[CompletedResourceRef, CompletedEvidence]:
    source, resource_type = _map_snapshot_identity(snapshot)
    title = _snapshot_title(snapshot)
    excerpt = _snapshot_excerpt(snapshot)
    return (
        CompletedResourceRef(
            id=f"resource-ref-{run_id}-{snapshot.resource_type.value}-{snapshot.resource_id}",
            source=source,
            resource_type=resource_type,
            resource_id=snapshot.resource_id,
            parent_resource_id=snapshot.parent_id,
            canonical_url=_optional_str(snapshot.payload.get("canonical_url")),
            title=title,
            event_time_ms=None,
            version_token=snapshot.version,
            metadata_json=dumps(_snapshot_metadata(snapshot), sort_keys=True),
        ),
        CompletedEvidence(
            id=f"evidence-{run_id}-{snapshot.resource_type.value}-{snapshot.resource_id}",
            origin_type=EvidenceOriginType.GOOGLE_RESOURCE,
            kind=snapshot.resource_type.value.upper(),
            excerpt=excerpt,
            locator_json=None,
            resource_ref_id=f"resource-ref-{run_id}-{snapshot.resource_type.value}-{snapshot.resource_id}",
        ),
    )


def _map_snapshot_identity(snapshot: ResourceSnapshot) -> tuple[ResourceSource, StoredResourceType]:
    mapping = {
        "gmail_thread": (ResourceSource.GMAIL, StoredResourceType.THREAD),
        "gmail_message": (ResourceSource.GMAIL, StoredResourceType.MESSAGE),
        "gmail_draft": (ResourceSource.GMAIL, StoredResourceType.MESSAGE),
        "task_list": (ResourceSource.TASKS, StoredResourceType.TASK_LIST),
        "task": (ResourceSource.TASKS, StoredResourceType.TASK),
        "calendar": (ResourceSource.CALENDAR, StoredResourceType.CALENDAR),
        "calendar_event": (ResourceSource.CALENDAR, StoredResourceType.EVENT),
        "calendar_freebusy": (ResourceSource.CALENDAR, StoredResourceType.CALENDAR),
    }
    return mapping[snapshot.resource_type.value]


def _snapshot_title(snapshot: ResourceSnapshot) -> str | None:
    for key in ("subject", "title", "snippet"):
        value = snapshot.payload.get(key)
        if isinstance(value, str) and value:
            return value[:200]
    return None


def _snapshot_excerpt(snapshot: ResourceSnapshot) -> str:
    if snapshot.resource_type.value == "gmail_message":
        subject = _optional_str(snapshot.payload.get("subject"))
        sender = _optional_str(snapshot.payload.get("from"))
        return f"Message from {sender or 'unknown'}{f' about {subject}' if subject else ''}"[:512]
    if snapshot.resource_type.value == "gmail_thread":
        return str(
            snapshot.payload.get("snippet", snapshot.payload.get("subject", snapshot.resource_id))
        )[:512]
    return str(
        snapshot.payload.get("title", snapshot.payload.get("subject", snapshot.resource_id))
    )[:512]


def _snapshot_metadata(snapshot: ResourceSnapshot) -> dict[str, object]:
    if snapshot.resource_type.value == "gmail_message":
        return {
            "from": _optional_str(snapshot.payload.get("from")),
            "to_count": len(snapshot.payload.get("to", []))
            if isinstance(snapshot.payload.get("to"), list)
            else 0,
            "attachment_count": (
                len(snapshot.payload.get("attachments", []))
                if isinstance(snapshot.payload.get("attachments"), list)
                else 0
            ),
        }
    if snapshot.resource_type.value == "gmail_thread":
        return {
            "subject": _optional_str(snapshot.payload.get("subject")),
            "participant_count": (
                len(snapshot.payload.get("participants", []))
                if isinstance(snapshot.payload.get("participants"), list)
                else 0
            ),
        }
    if snapshot.resource_type.value == "task":
        return {
            "status": _optional_str(snapshot.payload.get("status")),
            "due": snapshot.payload.get("due"),
        }
    if snapshot.resource_type.value == "calendar_event":
        return {
            "status": _optional_str(snapshot.payload.get("status")),
            "event_kind": _optional_str(snapshot.payload.get("event_kind")),
            "transparency": _optional_str(snapshot.payload.get("transparency")),
        }
    return {"title": _snapshot_title(snapshot)}


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _int_argument(value: object, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(value)
    raise TypeError("expected int-like argument")


def _string_tuple_argument(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("expected a list or tuple of strings")
    return tuple(str(item) for item in value)
