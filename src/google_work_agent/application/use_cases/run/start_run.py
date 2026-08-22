"""Canonical application use case for starting one isolated Run."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from json import dumps, loads

from google_work_agent.application.coordinator import QueueBusyError
from google_work_agent.application.write_persistence import emit_command_rejected_hash_mismatch
from google_work_agent.domain import ResultCode, RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected
from google_work_agent.domain.run.transitions.start_run import transition_start_run
from google_work_agent.ports import SelectedResourceRef
from google_work_agent.ports.models import (
    AuditEventRecord,
    CommandReceiptRecord,
    CommandReceiptStatus,
    MessageRecord,
    RunCreateRecord,
    TraceEventRecord,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


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
class StartRunResult:
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


class StartRunHandler:
    """Persist Run creation, initial USER Message, activity and receipt atomically."""

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

    def __call__(self, command: StartRunCommand) -> StartRunResult:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._resolve_existing_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    command=command,
                )

            if self._reserve_queue_slot is not None and not self._reserve_queue_slot(command.run_id):
                raise QueueBusyError()

            try:
                return self._start_new_run(unit_of_work=unit_of_work, command=command)
            except Exception:
                self._release(command.run_id)
                raise

    def _start_new_run(
        self,
        *,
        unit_of_work: UnitOfWork,
        command: StartRunCommand,
        receipt_already_received: bool = False,
    ) -> StartRunResult:
        now_ms = self._now_ms()
        if not receipt_already_received:
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
            response = StartRunResult(
                applied=False,
                result_code=ResultCode.STATE_CONFLICT.value,
                run_id=command.run_id,
                conversation_id=command.conversation_id,
                run_status=RunStatus.CREATED.value,
                run_version=0,
                user_message_id=command.user_message_id,
                workflow_key=command.workflow_key,
                enqueued=False,
                request_replayed=receipt_already_received,
                conflict_detail="request text exceeds message limit",
            )
            self._finish_receipt(unit_of_work, command.command_id, response, 0, now_ms)
            unit_of_work.commit()
            self._release(command.run_id)
            return response

        current_open = unit_of_work.runs.get_open_by_conversation(command.conversation_id)
        try:
            initial_status = transition_start_run(has_open_run=current_open is not None)
        except RunTransitionRejected:
            response = self._open_run_conflict(command=command, current_open=current_open)
            if receipt_already_received:
                response = replace(response, request_replayed=True)
            self._finish_receipt(
                unit_of_work,
                command.command_id,
                response,
                response.run_version,
                now_ms,
            )
            unit_of_work.commit()
            self._release(command.run_id)
            return response

        run = RunCreateRecord(
            id=command.run_id,
            conversation_id=command.conversation_id,
            entry_mode=command.entry_mode,
            status=initial_status,
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
            current_open = unit_of_work.runs.get_open_by_conversation(command.conversation_id)
            if current_open is None:
                raise
            response = self._open_run_conflict(command=command, current_open=current_open)
            if receipt_already_received:
                response = replace(response, request_replayed=True)
            self._finish_receipt(
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
                status=initial_status.value,
                duration_ms=None,
                payload_json=dumps(
                    {
                        "command_id": command.command_id,
                        "selected_resource_ids": list(command.selected_resource_ids),
                        "selected_resources": [asdict(resource) for resource in command.selected_resources],
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

        response = StartRunResult(
            applied=True,
            result_code=ResultCode.TRANSITION_APPLIED.value,
            run_id=command.run_id,
            conversation_id=command.conversation_id,
            run_status=initial_status.value,
            run_version=0,
            user_message_id=command.user_message_id,
            workflow_key=command.workflow_key,
            enqueued=True,
            request_replayed=receipt_already_received,
        )
        self._finish_receipt(unit_of_work, command.command_id, response, 0, now_ms)
        unit_of_work.commit()
        return response

    def _resolve_existing_receipt(
        self,
        *,
        unit_of_work: UnitOfWork,
        receipt: CommandReceiptRecord,
        command: StartRunCommand,
    ) -> StartRunResult:
        if receipt.request_hash != command.request_hash:
            emit_command_rejected_hash_mismatch(
                unit_of_work=unit_of_work,
                receipt=receipt,
                run_id=command.run_id,
                action_id=None,
                now_ms=self._now_ms(),
            )
            return StartRunResult(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                run_id=receipt.aggregate_id or command.run_id,
                conversation_id="",
                run_status="UNKNOWN",
                run_version=receipt.result_version or 0,
                user_message_id="",
                workflow_key="",
                enqueued=False,
                request_replayed=True,
                conflict_detail="command_id already exists with a different request_hash",
            )

        if receipt.status is not CommandReceiptStatus.RECEIVED and receipt.response_json is not None:
            response = StartRunResult(**loads(receipt.response_json))
            return replace(response, enqueued=False, request_replayed=True)

        if receipt.command_type != "StartRun" or receipt.aggregate_type != "Run" or receipt.aggregate_id != command.run_id:
            raise RuntimeError("StartRun receipt identity does not match command")

        run = unit_of_work.runs.get_by_id(command.run_id)
        message = unit_of_work.messages.get_by_id(command.user_message_id)

        if run is not None:
            if run.conversation_id != command.conversation_id:
                raise RuntimeError("StartRun receipt aggregate belongs to a different conversation")
            if (
                message is None
                or message.conversation_id != command.conversation_id
                or message.run_id != command.run_id
                or message.role != "USER"
                or message.content != command.request_text
            ):
                raise RuntimeError("StartRun receipt recovery found an incomplete aggregate mutation")

            stored_response = StartRunResult(
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
            self._finish_receipt(
                unit_of_work,
                command.command_id,
                stored_response,
                0,
                self._now_ms(),
            )
            unit_of_work.commit()
            return replace(stored_response, enqueued=False, request_replayed=True)

        if message is not None:
            raise RuntimeError("StartRun receipt recovery found USER Message without Run")

        if receipt.status is not CommandReceiptStatus.RECEIVED:
            raise RuntimeError("completed StartRun receipt is missing replay response")

        if self._reserve_queue_slot is not None and not self._reserve_queue_slot(command.run_id):
            raise QueueBusyError()

        try:
            return self._start_new_run(
                unit_of_work=unit_of_work,
                command=command,
                receipt_already_received=True,
            )
        except Exception:
            self._release(command.run_id)
            raise

    @staticmethod
    def _open_run_conflict(*, command: StartRunCommand, current_open: object) -> StartRunResult:
        if current_open is None:
            run_status = RunStatus.CREATED.value
            run_version = 0
        else:
            run_status = current_open.status.value
            run_version = current_open.version
        return StartRunResult(
            applied=False,
            result_code=ResultCode.STATE_CONFLICT.value,
            run_id=command.run_id,
            conversation_id=command.conversation_id,
            run_status=run_status,
            run_version=run_version,
            user_message_id=command.user_message_id,
            workflow_key=command.workflow_key,
            enqueued=False,
            request_replayed=False,
            conflict_detail="conversation already has an open run",
        )

    @staticmethod
    def _finish_receipt(
        unit_of_work: UnitOfWork,
        command_id: str,
        response: StartRunResult,
        result_version: int,
        completed_at_ms: int,
    ) -> None:
        unit_of_work.command_receipts.finish_json(
            command_id=command_id,
            applied=response.applied,
            result_code=ResultCode(response.result_code),
            result_version=result_version,
            response_json=dumps(asdict(response), sort_keys=True),
            completed_at_ms=completed_at_ms,
        )
