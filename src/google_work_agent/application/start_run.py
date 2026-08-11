"""Conversation and run API command services for the local FastAPI layer."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from json import dumps, loads
from typing import cast

from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    CommandResult,
    EffectType,
    EvidencePolicyInput,
    ResultCode,
    RunStatus,
    build_p0_tool_registry,
    calculate_canonical_json_hash,
    canonicalize_json_value,
    next_allowed_action_commands,
    validate_evidence_policy,
)
from google_work_agent.ports import (
    ActionRecord,
    AuditEventRecord,
    CommandReceiptRecord,
    CommandReceiptStatus,
    ConversationRecord,
    MessageRecord,
    RunCreateRecord,
    RunRecord,
    SelectedResourceRef,
    TraceEventRecord,
    UnitOfWork,
)


@dataclass(frozen=True, slots=True)
class CreateConversationCommand:
    command_id: str
    request_hash: str
    conversation_id: str
    account_id: str
    title: str
    api_contract_version: str


@dataclass(frozen=True, slots=True)
class CreateConversationResponse:
    applied: bool
    result_code: str
    conversation_id: str
    account_id: str
    title: str
    updated_at_ms: int
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class StartRunCommand:
    command_id: str
    request_hash: str
    conversation_id: str
    user_message_id: str
    run_id: str
    workflow_key: str
    request_text: str
    entry_mode: str
    selected_resource_ids: tuple[str, ...]
    requested_mode: str
    api_contract_version: str
    selected_resources: tuple[SelectedResourceRef, ...] = ()


@dataclass(frozen=True, slots=True)
class StartRunResponse:
    applied: bool
    result_code: str
    run_id: str
    conversation_id: str
    run_status: str
    run_version: int
    user_message_id: str
    workflow_key: str
    enqueued: bool
    request_replayed: bool
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class ModifyWriteActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    arguments_patch: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RejectWriteActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class ResumeRunCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_run_version: int
    resume_kind: str
    api_contract_version: str


@dataclass(frozen=True, slots=True)
class ResumeRunResponse:
    applied: bool
    result_code: str
    run_id: str
    run_status: str
    run_version: int
    should_enqueue: bool
    request_replayed: bool
    conflict_detail: str | None = None


type ReceiptResponse = (
    CreateConversationResponse | StartRunResponse | ResumeRunResponse | _ActionMutationResponse
)


class CreateConversationService:
    """Create conversations with durable idempotency."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: CreateConversationCommand) -> CreateConversationResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return cast(
                    CreateConversationResponse,
                    _resolve_json_receipt(
                        receipt=existing,
                        request_hash=command.request_hash,
                        response_type=CreateConversationResponse,
                    ),
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="CreateConversation",
                request_hash=command.request_hash,
                aggregate_type="Conversation",
                aggregate_id=command.conversation_id,
                created_at_ms=now_ms,
            )
            unit_of_work.conversations.add(
                ConversationRecord(
                    id=command.conversation_id,
                    account_id=command.account_id,
                    title=command.title,
                    created_at_ms=now_ms,
                    updated_at_ms=now_ms,
                )
            )
            response = CreateConversationResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                conversation_id=command.conversation_id,
                account_id=command.account_id,
                title=command.title,
                updated_at_ms=now_ms,
            )
            _finish_json_receipt(
                unit_of_work=unit_of_work,
                command_id=command.command_id,
                response=response,
                result_version=0,
                completed_at_ms=now_ms,
            )
            unit_of_work.commit()
            return response


class StartRunService:
    """Create a run and its initial user message before coordinator enqueue."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: StartRunCommand) -> StartRunResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                response = cast(
                    StartRunResponse,
                    _resolve_json_receipt(
                        receipt=existing,
                        request_hash=command.request_hash,
                        response_type=StartRunResponse,
                    ),
                )
                return StartRunResponse(
                    **{**asdict(response), "enqueued": False, "request_replayed": True}
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="StartRun",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )

            conversation = unit_of_work.conversations.get_by_id(command.conversation_id)
            if conversation is None:
                raise LookupError(f"conversation not found: {command.conversation_id}")

            if len(command.request_text.encode("utf-8")) > 65536:
                response = StartRunResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_id=command.run_id,
                    conversation_id=command.conversation_id,
                    run_status=RunStatus.CREATED.value,
                    run_version=0,
                    user_message_id=command.user_message_id,
                    workflow_key=command.workflow_key,
                    enqueued=False,
                    request_replayed=False,
                    conflict_detail="request text exceeds message limit",
                )
                _finish_json_receipt(unit_of_work, command.command_id, response, 0, now_ms)
                unit_of_work.commit()
                return response

            run = RunCreateRecord(
                id=command.run_id,
                conversation_id=command.conversation_id,
                entry_mode=command.entry_mode,
                status=RunStatus.CREATED,
                langgraph_thread_id=command.workflow_key,
                requested_mode=command.requested_mode,
                actual_runtime=None,
                budget_json="{}",
                version=0,
                started_at_ms=now_ms,
                finished_at_ms=None,
            )

            try:
                unit_of_work.runs.add(run)
            except sqlite3.IntegrityError:
                current_open = _find_open_run(unit_of_work, command.conversation_id)
                response = StartRunResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_id=command.run_id,
                    conversation_id=command.conversation_id,
                    run_status=(
                        current_open.status.value if current_open is not None else "CREATED"
                    ),
                    run_version=(current_open.version if current_open is not None else 0),
                    user_message_id=command.user_message_id,
                    workflow_key=command.workflow_key,
                    enqueued=False,
                    request_replayed=False,
                    conflict_detail="conversation already has an open run",
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

            unit_of_work.messages.add(
                MessageRecord(
                    id=command.user_message_id,
                    conversation_id=command.conversation_id,
                    run_id=command.run_id,
                    role="USER",
                    content=command.request_text,
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=command.run_id,
                    action_id=None,
                    event_type="RUN_CREATED",
                    status=RunStatus.CREATED.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {
                            "command_id": command.command_id,
                            "selected_resource_ids": list(command.selected_resource_ids),
                            "selected_resources": [
                                asdict(resource) for resource in command.selected_resources
                            ],
                            "workflow_key": command.workflow_key,
                            "requested_mode": command.requested_mode,
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                AuditEventRecord(
                    account_id=conversation.account_id,
                    run_id=command.run_id,
                    action_id=None,
                    actor_type="USER",
                    actor_id=conversation.account_id,
                    actor_display=None,
                    event_type="RUN_CREATED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata_json=dumps(
                        {
                            "command_id": command.command_id,
                            "conversation_id": command.conversation_id,
                            "entry_mode": command.entry_mode,
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )

            response = StartRunResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                run_id=command.run_id,
                conversation_id=command.conversation_id,
                run_status=RunStatus.CREATED.value,
                run_version=0,
                user_message_id=command.user_message_id,
                workflow_key=command.workflow_key,
                enqueued=True,
                request_replayed=False,
            )
            _finish_json_receipt(unit_of_work, command.command_id, response, 0, now_ms)
            unit_of_work.commit()
            return response


_MODIFIABLE_ACTION_STATUSES = frozenset({ActionStatus.PROPOSED.value, ActionStatus.APPROVED.value})


class ModifyWriteActionService:
    """Apply a user-supplied ``arguments_patch`` to a write action (FN-052)
    and revoke any Approval it invalidates.

    Scope is deliberately narrower than the bare domain transition table:
    only ``PROPOSED`` and ``APPROVED`` write actions may be content-edited
    here. ``FAILED`` retries go through ``prepare_write_retry`` and
    ``EXPIRED`` refresh is a separate, not-yet-implemented
    ``refresh_expired_action`` command -- both keep their own contracts
    instead of being reachable through this endpoint.

    FN-052 also requires: (1) only its own fixed field list per tool is
    patchable -- see ``ToolRegistryEntry.modify_patchable_fields``, which is
    intentionally narrower than a tool's raw MCP dispatch capability; (2) a
    no-op patch (empty, or equal to the current Canonical Arguments) applies
    nothing and must not revoke an ACTIVE Approval; (3) Schema and Policy are
    re-checked (field allowlist + ``validate_evidence_policy``), while
    Duplicate/Conflict re-validation (FN-031/FN-032) has no deterministic
    validator yet and is marked, not faked, at its call seam; (4) direct
    dependents of the modified action that are already APPROVED have their
    ACTIVE Approval revoked too, so a stale dependent Approval can never
    authorize a Claim -- see ``_revoke_stale_dependent_approvals``.
    """

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._registry = build_p0_tool_registry()

    def __call__(self, command: ModifyWriteActionCommand) -> dict[str, object]:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return cast(
                    dict[str, object],
                    asdict(
                        cast(
                            _ActionMutationResponse,
                            _resolve_json_receipt(
                                receipt=existing,
                                request_hash=command.request_hash,
                                response_type=_ActionMutationResponse,
                            ),
                        )
                    ),
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="ModifyWriteAction",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            effect_type = EffectType(action.effect_type)

            if effect_type is EffectType.READ or action.status not in _MODIFIABLE_ACTION_STATUSES:
                return self._finish(
                    unit_of_work,
                    command=command,
                    now_ms=now_ms,
                    response=_ActionMutationResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=tuple(
                            item.value
                            for item in next_allowed_action_commands(
                                ActionStatus(action.status), effect_type=effect_type
                            )
                        ),
                        conflict_detail=(
                            "modify_action requires a PROPOSED or APPROVED write action; "
                            "use prepare-retry for FAILED actions"
                        ),
                    ),
                )

            entry = self._registry.require(action.tool_name)
            unknown_fields = sorted(set(command.arguments_patch) - entry.modify_patchable_fields)
            if unknown_fields:
                return self._finish(
                    unit_of_work,
                    command=command,
                    now_ms=now_ms,
                    response=_ActionMutationResponse(
                        applied=False,
                        result_code=ResultCode.SCHEMA_VIOLATION.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=tuple(
                            item.value
                            for item in next_allowed_action_commands(
                                ActionStatus(action.status), effect_type=effect_type
                            )
                        ),
                        conflict_detail=f"unsupported arguments_patch fields: {unknown_fields}",
                    ),
                )

            new_arguments = _apply_arguments_patch(
                loads(action.arguments_json), command.arguments_patch
            )
            new_arguments_hash = calculate_canonical_json_hash(new_arguments)

            # FN-052 no-op guard: a patch that is empty, or that only restates
            # fields already equal to the current Canonical Arguments, must
            # not mutate anything. In particular it must never revoke an
            # existing ACTIVE Approval -- there is nothing to re-approve.
            if new_arguments_hash == action.arguments_hash:
                return self._finish(
                    unit_of_work,
                    command=command,
                    now_ms=now_ms,
                    response=_ActionMutationResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=tuple(
                            item.value
                            for item in next_allowed_action_commands(
                                ActionStatus(action.status), effect_type=effect_type
                            )
                        ),
                        conflict_detail=(
                            "arguments_patch does not change any canonical argument value"
                        ),
                    ),
                )

            # Evidence/target linkage cannot change through a Modify patch, so
            # this reuses the exact inputs already satisfied when the action
            # was first planned -- a defensive re-check, not a new gate.
            evidence_count = len(unit_of_work.evidence.list_by_action(action.id))
            validate_evidence_policy(
                EvidencePolicyInput(
                    evidence_count=evidence_count,
                    requires_existing_resource=effect_type
                    in {EffectType.UPDATE, EffectType.DELETE},
                    has_user_selected_resource=action.target_resource_ref_id is not None,
                    has_explicit_resource_relation=action.target_resource_ref_id is not None,
                )
            )

            # FN-052 also requires re-checking Duplicate (FN-031) and Conflict
            # (FN-032) against `new_arguments` here, before persisting. No
            # deterministic FN-031/FN-032 validator exists in this codebase
            # yet (GAP-F3 prerequisite) -- this is the exact seam to call it
            # from once it lands. Do not approximate it with an LLM judgment
            # or a string heuristic in the meantime.

            result = unit_of_work.actions.modify_write(
                action.id,
                expected_version=command.expected_version,
                updated_at_ms=now_ms,
                arguments_json=canonicalize_json_value(new_arguments),
                arguments_hash=calculate_canonical_json_hash(new_arguments),
            )
            if not result.applied:
                return self._finish(
                    unit_of_work,
                    command=command,
                    now_ms=now_ms,
                    response=_ActionMutationResponse(
                        applied=False,
                        result_code=result.result_code.value,
                        action_id=action.id,
                        action_status=result.current_status.value,
                        action_version=result.current_version,
                        next_allowed_commands=tuple(
                            item.value for item in result.next_allowed_commands
                        ),
                        conflict_detail=result.conflict_detail,
                    ),
                )

            # A stale ACTIVE Approval must never authorize execution of the
            # arguments it was not issued for. Revoking is a no-op when the
            # action was PROPOSED and had no Approval yet.
            revoked_approval_ids = unit_of_work.approvals.revoke_active_by_action(action.id)
            run_id = _run_id_for_action(unit_of_work, action.id)
            _revoke_stale_dependent_approvals(
                unit_of_work=unit_of_work,
                modified_action_id=action.id,
                run_id=run_id,
                command_id=command.command_id,
                now_ms=now_ms,
            )

            response = _ActionMutationResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                action_id=action.id,
                action_status=result.current_status.value,
                action_version=result.current_version,
                next_allowed_commands=tuple(item.value for item in result.next_allowed_commands),
            )
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=run_id,
                    action_id=action.id,
                    event_type="ACTION_MODIFIED",
                    status=result.current_status.value,
                    duration_ms=None,
                    payload_json=dumps({"command_id": command.command_id}, sort_keys=True),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _modify_audit_event(
                    run_id=run_id,
                    action_id=action.id,
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={
                        "command_id": command.command_id,
                        "revoked_approval_ids": list(revoked_approval_ids),
                    },
                    created_at_ms=now_ms,
                )
            )
            return self._finish(unit_of_work, command=command, now_ms=now_ms, response=response)

    @staticmethod
    def _finish(
        unit_of_work: UnitOfWork,
        *,
        command: ModifyWriteActionCommand,
        now_ms: int,
        response: _ActionMutationResponse,
    ) -> dict[str, object]:
        _finish_json_receipt(
            unit_of_work,
            command.command_id,
            response,
            response.action_version,
            now_ms,
        )
        unit_of_work.commit()
        return cast(dict[str, object], asdict(response))


def _apply_arguments_patch(
    current_arguments: dict[str, object],
    patch: dict[str, object],
) -> dict[str, object]:
    """Merge business-field-only ``patch`` into a write action's arguments.

    Every mutable business field lives under the ``payload`` container that
    CREATE/UPDATE write tools already use; target/container identity fields
    stay outside ``payload`` and are never part of any tool's patchable set,
    so they are always carried through unchanged.
    """

    if not patch:
        return current_arguments
    merged = dict(current_arguments)
    payload = current_arguments.get("payload")
    new_payload = dict(payload) if isinstance(payload, dict) else {}
    new_payload.update(patch)
    merged["payload"] = new_payload
    return merged


def _modify_audit_event(
    *,
    run_id: str,
    action_id: str,
    outcome: str,
    metadata: dict[str, object],
    created_at_ms: int,
    event_type: str = "ACTION_MODIFIED",
) -> AuditEventRecord:
    return AuditEventRecord(
        account_id=None,
        run_id=run_id,
        action_id=action_id,
        actor_type="AGENT",
        actor_id="modify_write_action_service",
        actor_display="ModifyWriteActionService",
        event_type=event_type,
        outcome=outcome,
        metadata_json=dumps(metadata, sort_keys=True),
        created_at_ms=created_at_ms,
    )


def _revoke_stale_dependent_approvals(
    *,
    unit_of_work: UnitOfWork,
    modified_action_id: str,
    run_id: str,
    command_id: str,
    now_ms: int,
) -> None:
    """Revoke ACTIVE Approvals on direct dependents of a just-modified action.

    08-sequence-design.md requires Modify to trigger a plan/dependency
    re-review; 03-system-architecture.md requires dependent Arguments
    affected by an upstream edit to be re-planned. Neither a Supervisor
    re-review service nor an Action re-planning service exists yet (tracked
    as a follow-on GAP), so this does not attempt either. It only enforces
    the hard safety floor that must hold regardless: an already-APPROVED
    dependent action must never remain executable on an Approval issued
    before its upstream action changed. The dependent's own status/version
    is intentionally left untouched -- there is no Domain command yet for
    "APPROVED action needs a fresh look without content changing" (the same
    gap blocking `refresh_expired_action`), so cancelling or re-approving it
    is left to the user via the existing CancelPendingAction/PROPOSED path.

    SaveWritePlanService now populates `action_dependencies` for WRITE
    actions (GAP-F3 prerequisite: WRITE Action Dependency Persistence), so
    `list_dependents` returns real edges once a plan with
    `depends_on_action_ids` has been saved.
    """

    for dependent_id in unit_of_work.action_dependencies.list_dependents(modified_action_id):
        dependent = unit_of_work.actions.get_by_id(dependent_id)
        if dependent is None or dependent.status != ActionStatus.APPROVED.value:
            continue
        revoked_ids = unit_of_work.approvals.revoke_active_by_action(dependent_id)
        if not revoked_ids:
            continue
        unit_of_work.traces.add(
            TraceEventRecord(
                run_id=run_id,
                action_id=dependent_id,
                event_type="ACTION_DEPENDENT_APPROVAL_REVOKED",
                status=dependent.status,
                duration_ms=None,
                payload_json=dumps(
                    {
                        "command_id": command_id,
                        "modified_action_id": modified_action_id,
                        "revoked_approval_ids": list(revoked_ids),
                    },
                    sort_keys=True,
                ),
                created_at_ms=now_ms,
            )
        )
        unit_of_work.audits.add(
            _modify_audit_event(
                run_id=run_id,
                action_id=dependent_id,
                outcome=ResultCode.TRANSITION_APPLIED.value,
                metadata={
                    "command_id": command_id,
                    "modified_action_id": modified_action_id,
                    "revoked_approval_ids": list(revoked_ids),
                },
                created_at_ms=now_ms,
                event_type="ACTION_DEPENDENT_APPROVAL_REVOKED",
            )
        )


class RejectWriteActionService:
    """Expose the domain reject transition for existing write actions."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: RejectWriteActionCommand) -> dict[str, object]:
        return _mutate_write_action(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
            command_id=command.command_id,
            request_hash=command.request_hash,
            action_id=command.action_id,
            expected_version=command.expected_version,
            command_type="RejectWriteAction",
            transition_name="ACTION_REJECTED",
            mutate=lambda unit_of_work, updated_at_ms: unit_of_work.actions.reject_write(
                command.action_id,
                expected_version=command.expected_version,
                updated_at_ms=updated_at_ms,
            ),
        )


class ResumeRunService:
    """Validate one resume command and persist an idempotent receipt."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: ResumeRunCommand) -> ResumeRunResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                response = cast(
                    ResumeRunResponse,
                    _resolve_json_receipt(
                        receipt=existing,
                        request_hash=command.request_hash,
                        response_type=ResumeRunResponse,
                    ),
                )
                return ResumeRunResponse(
                    **{
                        **asdict(response),
                        "should_enqueue": False,
                        "request_replayed": True,
                    }
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="ResumeRun",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            run = _require_run(unit_of_work, command.run_id)
            latest_plan = _latest_plan_id(unit_of_work, command.run_id)
            unknown_result_exists = False
            if latest_plan is not None:
                unknown_result_exists = any(
                    action.status == ActionStatus.UNKNOWN_RESULT.value
                    for action in unit_of_work.actions.list_by_plan(latest_plan)
                )

            allowed_statuses = {
                "CONFIRMATION": {RunStatus.WAITING_CONFIRMATION},
                "REAUTH_COMPLETED": {RunStatus.REAUTH_REQUIRED},
                "SAFE_CHECKPOINT_RESUME": {RunStatus.BLOCKED},
                "RECOVERY_RECHECK": {RunStatus.RECOVERY_REQUIRED},
            }
            if command.expected_run_version != run.version:
                response = ResumeRunResponse(
                    applied=False,
                    result_code=ResultCode.VERSION_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    should_enqueue=False,
                    request_replayed=False,
                    conflict_detail="expected_run_version does not match current version",
                )
            elif unknown_result_exists and command.resume_kind != "RECOVERY_RECHECK":
                response = ResumeRunResponse(
                    applied=False,
                    result_code=ResultCode.RECOVERY_REQUIRED.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    should_enqueue=False,
                    request_replayed=False,
                    conflict_detail="unknown write results must be resolved before resume",
                )
            elif run.status not in allowed_statuses.get(command.resume_kind, set()):
                response = ResumeRunResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    should_enqueue=False,
                    request_replayed=False,
                    conflict_detail="run status does not allow manual resume",
                )
            else:
                response = ResumeRunResponse(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    should_enqueue=True,
                    request_replayed=False,
                )
            _finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
            unit_of_work.commit()
            return response


def _mutate_write_action(
    *,
    unit_of_work_factory: Callable[[], UnitOfWork],
    now_ms: Callable[[], int],
    command_id: str,
    request_hash: str,
    action_id: str,
    expected_version: int,
    command_type: str,
    transition_name: str,
    mutate: Callable[[UnitOfWork, int], CommandResult[ActionStatus, ActionCommand]],
) -> dict[str, object]:
    with unit_of_work_factory() as unit_of_work:
        existing = unit_of_work.command_receipts.get_by_command_id(command_id)
        if existing is not None:
            return cast(
                dict[str, object],
                asdict(
                    cast(
                        _ActionMutationResponse,
                        _resolve_json_receipt(
                            receipt=existing,
                            request_hash=request_hash,
                            response_type=_ActionMutationResponse,
                        ),
                    )
                ),
            )

        updated_at_ms = now_ms()
        unit_of_work.command_receipts.add_received(
            command_id=command_id,
            command_type=command_type,
            request_hash=request_hash,
            aggregate_type="Action",
            aggregate_id=action_id,
            created_at_ms=updated_at_ms,
        )
        action = _require_action(unit_of_work, action_id)
        result = mutate(unit_of_work, updated_at_ms)
        response = _ActionMutationResponse(
            applied=result.applied,
            result_code=result.result_code.value,
            action_id=action.id,
            action_status=result.current_status.value,
            action_version=result.current_version,
            next_allowed_commands=tuple(
                item.value
                for item in next_allowed_action_commands(
                    result.current_status,
                    effect_type=EffectType(action.effect_type),
                )
            ),
            conflict_detail=result.conflict_detail,
        )
        if result.applied:
            run_id = _run_id_for_action(unit_of_work, action_id)
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=run_id,
                    action_id=action_id,
                    event_type=transition_name,
                    status=result.current_status.value,
                    duration_ms=None,
                    payload_json=dumps({"command_id": command_id}, sort_keys=True),
                    created_at_ms=updated_at_ms,
                )
            )
        _finish_json_receipt(
            unit_of_work,
            command_id,
            response,
            response.action_version,
            updated_at_ms,
        )
        unit_of_work.commit()
        return cast(dict[str, object], asdict(response))


@dataclass(frozen=True, slots=True)
class _ActionMutationResponse:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None


def _resolve_json_receipt(
    *,
    receipt: CommandReceiptRecord,
    request_hash: str,
    response_type: type[object],
) -> ReceiptResponse:
    from json import loads

    request_hash_value = receipt.request_hash
    if request_hash_value != request_hash:
        aggregate_id = receipt.aggregate_id or ""
        result_version = receipt.result_version or 0
        if response_type is CreateConversationResponse:
            return CreateConversationResponse(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                conversation_id=aggregate_id,
                account_id="",
                title="",
                updated_at_ms=0,
                conflict_detail="command_id already exists with a different request_hash",
            )
        if response_type is StartRunResponse:
            return StartRunResponse(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                run_id=aggregate_id,
                conversation_id="",
                run_status="UNKNOWN",
                run_version=result_version,
                user_message_id="",
                workflow_key="",
                enqueued=False,
                request_replayed=True,
                conflict_detail="command_id already exists with a different request_hash",
            )
        if response_type is ResumeRunResponse:
            return ResumeRunResponse(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                run_id=aggregate_id,
                run_status="UNKNOWN",
                run_version=result_version,
                should_enqueue=False,
                request_replayed=True,
                conflict_detail="command_id already exists with a different request_hash",
            )
        return _ActionMutationResponse(
            applied=False,
            result_code=ResultCode.DUPLICATE_COMMAND.value,
            action_id=aggregate_id,
            action_status="UNKNOWN",
            action_version=result_version,
            next_allowed_commands=(),
            conflict_detail="command_id already exists with a different request_hash",
        )

    response_json = receipt.response_json
    status = receipt.status
    if response_json is None or status is CommandReceiptStatus.RECEIVED:
        raise RuntimeError("RECEIVED receipt recovery requires aggregate-specific handling")
    payload = loads(response_json)
    if "next_allowed_commands" in payload:
        payload["next_allowed_commands"] = tuple(payload["next_allowed_commands"])
    return cast(ReceiptResponse, response_type(**payload))


def _finish_json_receipt(
    unit_of_work: UnitOfWork,
    command_id: str,
    response: ReceiptResponse,
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


def _latest_plan_id(unit_of_work: UnitOfWork, run_id: str) -> str | None:
    plans = unit_of_work.plans.list_by_run(run_id)
    if not plans:
        return None
    return plans[-1].id


def _run_id_for_action(unit_of_work: UnitOfWork, action_id: str) -> str:
    action = _require_action(unit_of_work, action_id)
    plan = unit_of_work.plans.get_by_id(action.plan_id)
    if plan is None:
        raise LookupError(f"plan not found for action: {action_id}")
    return plan.run_id


def _find_open_run(unit_of_work: UnitOfWork, conversation_id: str) -> RunRecord | None:
    del unit_of_work, conversation_id
    return None


def _require_run(unit_of_work: UnitOfWork, run_id: str) -> RunRecord:
    run = unit_of_work.runs.get_by_id(run_id)
    if run is None:
        raise LookupError(f"run not found: {run_id}")
    return run


def _require_action(unit_of_work: UnitOfWork, action_id: str) -> ActionRecord:
    action = unit_of_work.actions.get_by_id(action_id)
    if action is None:
        raise LookupError(f"action not found: {action_id}")
    return action
