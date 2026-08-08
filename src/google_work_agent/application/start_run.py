"""Conversation and run API command services for the local FastAPI layer."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps
from typing import cast

from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    CommandResult,
    EffectType,
    ResultCode,
    RunStatus,
    next_allowed_action_commands,
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


class ModifyWriteActionService:
    """Expose the domain modify transition for existing write actions."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: ModifyWriteActionCommand) -> dict[str, object]:
        return _mutate_write_action(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
            command_id=command.command_id,
            request_hash=command.request_hash,
            action_id=command.action_id,
            expected_version=command.expected_version,
            command_type="ModifyWriteAction",
            transition_name="ACTION_MODIFIED",
            mutate=lambda unit_of_work, updated_at_ms: unit_of_work.actions.modify_write(
                command.action_id,
                expected_version=command.expected_version,
                updated_at_ms=updated_at_ms,
            ),
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
                RunStatus.WAITING_CONFIRMATION,
                RunStatus.WAITING_APPROVAL,
                RunStatus.BLOCKED,
            }
            if unknown_result_exists:
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
            elif run.status not in allowed_statuses:
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
