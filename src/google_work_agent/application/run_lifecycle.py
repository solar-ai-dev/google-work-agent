"""Start and resume use cases for the persisted run lifecycle."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from json import dumps
from typing import cast

from google_work_agent.application.coordinator import QueueBusyError
from google_work_agent.application.run_command_receipts import (
    finish_json_receipt as _finish_json_receipt,
)
from google_work_agent.application.run_command_receipts import (
    resolve_existing_receipt as _resolve_existing_receipt,
)
from google_work_agent.application.run_contracts import (
    ResumeRunCommand,
    ResumeRunResponse,
    StartRunCommand,
    StartRunResponse,
)
from google_work_agent.domain import ActionStatus, ResultCode, RunStatus
from google_work_agent.ports import (
    AuditEventRecord,
    MessageRecord,
    RunCreateRecord,
    RunRecord,
    TraceEventRecord,
    UnitOfWork,
)


class StartRunService:
    """Create a run and its initial user message before coordinator enqueue."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        reserve_queue_slot: Callable[[str], bool] | None = None,
        release_queue_slot: Callable[[str], None] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._reserve_queue_slot = reserve_queue_slot
        self._release_queue_slot = release_queue_slot

    def _release(self, run_id: str) -> None:
        if self._release_queue_slot is not None:
            self._release_queue_slot(run_id)

    def __call__(self, command: StartRunCommand) -> StartRunResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                response = cast(
                    StartRunResponse,
                    _resolve_existing_receipt(
                        unit_of_work=unit_of_work,
                        receipt=existing,
                        request_hash=command.request_hash,
                        response_type=StartRunResponse,
                        run_id=command.run_id,
                        now_ms=self._now_ms(),
                    ),
                )
                return StartRunResponse(
                    **{**asdict(response), "enqueued": False, "request_replayed": True}
                )

            # Claim coordinator queue admission for this run before any Domain
            # row commits, so a full/stopped queue rejects the request instead
            # of leaving a silent orphan CREATED row behind. Everything past
            # this point that returns without enqueued=True must release the
            # reservation (explicitly below, or via the except clause for any
            # unexpected failure).
            if self._reserve_queue_slot is not None and not self._reserve_queue_slot(
                command.run_id
            ):
                raise QueueBusyError()

            try:
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
                    self._release(command.run_id)
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
                    self._release(command.run_id)
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
                unit_of_work.conversations.touch(command.conversation_id, updated_at_ms=now_ms)
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
            except Exception:
                self._release(command.run_id)
                raise


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
                    _resolve_existing_receipt(
                        unit_of_work=unit_of_work,
                        receipt=existing,
                        request_hash=command.request_hash,
                        response_type=ResumeRunResponse,
                        run_id=command.run_id,
                        now_ms=self._now_ms(),
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


def _latest_plan_id(unit_of_work: UnitOfWork, run_id: str) -> str | None:
    plans = unit_of_work.plans.list_by_run(run_id)
    if not plans:
        return None
    return plans[-1].id


def _find_open_run(unit_of_work: UnitOfWork, conversation_id: str) -> RunRecord | None:
    del unit_of_work, conversation_id
    return None


def _require_run(unit_of_work: UnitOfWork, run_id: str) -> RunRecord:
    run = unit_of_work.runs.get_by_id(run_id)
    if run is None:
        raise LookupError(f"run not found: {run_id}")
    return run
