"""Start a persisted run and enqueue its workflow exactly once."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from json import dumps
from typing import cast

from google_work_agent.application.coordinator import QueueBusyError
from google_work_agent.application.run_command_receipts import finish_json_receipt, resolve_existing_receipt
from google_work_agent.application.run_contracts import StartRunCommand, StartRunResponse as StartRunResult
from google_work_agent.domain import ResultCode, RunStatus
from google_work_agent.ports import AuditEventRecord, MessageRecord, RunCreateRecord, TraceEventRecord, UnitOfWork


class StartRunHandler:
    """Own run creation, durable input persistence, and coordinator handoff."""

    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int], reserve_queue_slot: Callable[[str], bool] | None, release_queue_slot: Callable[[str], None] | None, confirm_start: Callable[..., None]) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._reserve_queue_slot = reserve_queue_slot
        self._release_queue_slot = release_queue_slot
        self._confirm_start = confirm_start

    @classmethod
    def from_legacy_service_supplier(cls, service_supplier: Callable[[], object], coordinator: object) -> "StartRunHandler":
        service = service_supplier()
        return cls(unit_of_work_factory=service._unit_of_work_factory, now_ms=service._now_ms, reserve_queue_slot=service._reserve_queue_slot, release_queue_slot=service._release_queue_slot, confirm_start=coordinator.confirm_start)  # type: ignore[attr-defined]

    def __call__(self, command: StartRunCommand, *, request_id: str) -> StartRunResult:
        result = self._persist(command)
        if result.applied and result.enqueued:
            self._confirm_start(run_id=result.run_id, request_id=request_id, command_id=command.command_id)
        return result

    def _release(self, run_id: str) -> None:
        if self._release_queue_slot is not None:
            self._release_queue_slot(run_id)

    def _persist(self, command: StartRunCommand) -> StartRunResult:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                response = cast(StartRunResult, resolve_existing_receipt(unit_of_work=unit_of_work, receipt=existing, request_hash=command.request_hash, response_type=StartRunResult, run_id=command.run_id, now_ms=self._now_ms()))
                return StartRunResult(**{**asdict(response), "enqueued": False, "request_replayed": True})
            if self._reserve_queue_slot is not None and not self._reserve_queue_slot(command.run_id):
                raise QueueBusyError()
            try:
                now_ms = self._now_ms()
                unit_of_work.command_receipts.add_received(command_id=command.command_id, command_type="StartRun", request_hash=command.request_hash, aggregate_type="Run", aggregate_id=command.run_id, created_at_ms=now_ms)
                conversation = unit_of_work.conversations.get_by_id(command.conversation_id)
                if conversation is None:
                    raise LookupError(f"conversation not found: {command.conversation_id}")
                if len(command.request_text.encode("utf-8")) > 65536:
                    response = StartRunResult(applied=False, result_code=ResultCode.STATE_CONFLICT.value, run_id=command.run_id, conversation_id=command.conversation_id, run_status=RunStatus.CREATED.value, run_version=0, user_message_id=command.user_message_id, workflow_key=command.workflow_key, enqueued=False, request_replayed=False, conflict_detail="request text exceeds message limit")
                    finish_json_receipt(unit_of_work, command.command_id, response, 0, now_ms)
                    unit_of_work.commit()
                    self._release(command.run_id)
                    return response
                run = RunCreateRecord(id=command.run_id, conversation_id=command.conversation_id, entry_mode=command.entry_mode, status=RunStatus.CREATED, langgraph_thread_id=command.workflow_key, requested_mode=command.requested_mode, actual_runtime=None, budget_json="{}", version=0, started_at_ms=now_ms, finished_at_ms=None)
                try:
                    unit_of_work.runs.add(run)
                except sqlite3.IntegrityError:
                    response = StartRunResult(applied=False, result_code=ResultCode.STATE_CONFLICT.value, run_id=command.run_id, conversation_id=command.conversation_id, run_status=RunStatus.CREATED.value, run_version=0, user_message_id=command.user_message_id, workflow_key=command.workflow_key, enqueued=False, request_replayed=False, conflict_detail="conversation already has an open run")
                    finish_json_receipt(unit_of_work, command.command_id, response, 0, now_ms)
                    unit_of_work.commit()
                    self._release(command.run_id)
                    return response
                unit_of_work.messages.add(MessageRecord(id=command.user_message_id, conversation_id=command.conversation_id, run_id=command.run_id, role="USER", content=command.request_text, created_at_ms=now_ms))
                unit_of_work.conversations.touch(command.conversation_id, updated_at_ms=now_ms)
                unit_of_work.traces.add(TraceEventRecord(run_id=command.run_id, action_id=None, event_type="RUN_CREATED", status=RunStatus.CREATED.value, duration_ms=None, payload_json=dumps({"command_id": command.command_id, "selected_resource_ids": list(command.selected_resource_ids), "selected_resources": [asdict(resource) for resource in command.selected_resources], "workflow_key": command.workflow_key, "requested_mode": command.requested_mode}, sort_keys=True), created_at_ms=now_ms))
                unit_of_work.audits.add(AuditEventRecord(account_id=conversation.account_id, run_id=command.run_id, action_id=None, actor_type="USER", actor_id=conversation.account_id, actor_display=None, event_type="RUN_CREATED", outcome=ResultCode.TRANSITION_APPLIED.value, metadata_json=dumps({"command_id": command.command_id, "conversation_id": command.conversation_id, "entry_mode": command.entry_mode}, sort_keys=True), created_at_ms=now_ms))
                response = StartRunResult(applied=True, result_code=ResultCode.TRANSITION_APPLIED.value, run_id=command.run_id, conversation_id=command.conversation_id, run_status=RunStatus.CREATED.value, run_version=0, user_message_id=command.user_message_id, workflow_key=command.workflow_key, enqueued=True, request_replayed=False)
                finish_json_receipt(unit_of_work, command.command_id, response, 0, now_ms)
                unit_of_work.commit()
                return response
            except Exception:
                self._release(command.run_id)
                raise


__all__ = ["QueueBusyError", "StartRunCommand", "StartRunHandler", "StartRunResult"]
