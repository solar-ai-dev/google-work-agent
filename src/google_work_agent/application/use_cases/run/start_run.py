"""Canonical application use case for starting one isolated Run."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads

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
    PersistedAuditEventRecord,
    PersistedTraceEventRecord,
    RunCreateRecord,
    TraceEventRecord,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import (
    GraphProfileIdV1,
    RunExecutionRefV1,
    WorkflowHandoffStageV1,
)


@dataclass(frozen=True, slots=True)
class StartRunCommand:
    command_id: str
    request_hash: str
    conversation_id: str
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
    handoff_id: str
    enqueued: bool
    request_replayed: bool
    conflict_detail: str | None = None


class StartRunHandler:
    """Atomically create one Run + USER Message + WorkflowBinding + START WorkflowHandoff(PENDING).

    Browser never chooses run_id/user_message_id/workflow_key/handoff_id; this
    handler preallocates them only on the fresh (no existing receipt) path so
    idempotent retries always resolve through the durable CommandReceipt
    instead of minting a second aggregate identity.
    """

    _EVIDENCE_PAGE_SIZE = 100

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        id_factory: Callable[[], str],
        graph_profile: GraphProfileIdV1,
        graph_version: str,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._graph_version = graph_version

    def __call__(self, command: StartRunCommand) -> StartRunResult:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._resolve_existing_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    command=command,
                )
            return self._start_new_run(unit_of_work=unit_of_work, command=command)

    def _start_new_run(
        self,
        *,
        unit_of_work: UnitOfWork,
        command: StartRunCommand,
    ) -> StartRunResult:
        now_ms = self._now_ms()
        run_id = self._id_factory()
        user_message_id = self._id_factory()
        workflow_key = self._id_factory()
        handoff_id = self._id_factory()

        unit_of_work.command_receipts.add_received(
            command_id=command.command_id,
            command_type="StartRun",
            request_hash=command.request_hash,
            aggregate_type="Run",
            aggregate_id=run_id,
            created_at_ms=now_ms,
        )

        conversation = unit_of_work.conversations.get(command.conversation_id)
        if conversation is None:
            raise LookupError(f"conversation not found: {command.conversation_id}")

        if len(command.request_text.encode("utf-8")) > 65536:
            response = StartRunResult(
                applied=False,
                result_code=ResultCode.STATE_CONFLICT.value,
                run_id=run_id,
                conversation_id=command.conversation_id,
                run_status=RunStatus.CREATED.value,
                run_version=0,
                user_message_id=user_message_id,
                workflow_key=workflow_key,
                handoff_id="",
                enqueued=False,
                request_replayed=False,
                conflict_detail="request text exceeds message limit",
            )
            self._finish_receipt(unit_of_work, command.command_id, response, 0, now_ms)
            unit_of_work.commit()
            return response

        current_open = unit_of_work.runs.find_open_by_conversation(command.conversation_id)
        try:
            initial_status = transition_start_run(has_open_run=current_open is not None)
        except RunTransitionRejected:
            response = self._open_run_conflict(
                run_id=run_id,
                conversation_id=command.conversation_id,
                user_message_id=user_message_id,
                workflow_key=workflow_key,
                current_open=current_open,
            )
            self._finish_receipt(
                unit_of_work, command.command_id, response, response.run_version, now_ms
            )
            unit_of_work.commit()
            return response

        run = RunCreateRecord(
            id=run_id,
            conversation_id=command.conversation_id,
            entry_mode=command.entry_mode,
            status=initial_status,
            langgraph_thread_id=workflow_key,
            requested_mode=command.requested_mode,
            actual_runtime=None,
            budget_json="{}",
            version=0,
            started_at_ms=now_ms,
            finished_at_ms=None,
        )

        try:
            unit_of_work.runs.create(run)
        except sqlite3.IntegrityError:
            current_open = unit_of_work.runs.find_open_by_conversation(command.conversation_id)
            if current_open is None:
                raise
            response = self._open_run_conflict(
                run_id=run_id,
                conversation_id=command.conversation_id,
                user_message_id=user_message_id,
                workflow_key=workflow_key,
                current_open=current_open,
            )
            self._finish_receipt(
                unit_of_work, command.command_id, response, response.run_version, now_ms
            )
            unit_of_work.commit()
            return response

        unit_of_work.messages.append_user_message(
            MessageRecord(
                id=user_message_id,
                conversation_id=command.conversation_id,
                run_id=run_id,
                role="USER",
                content=command.request_text,
                created_at_ms=now_ms,
            )
        )
        unit_of_work.conversations.touch_updated_at(command.conversation_id, updated_at_ms=now_ms)

        unit_of_work.workflow_handoffs.stage_pending(
            WorkflowHandoffStageV1(
                schema_version=1,
                handoff_id=handoff_id,
                trigger_command_id=command.command_id,
                execution=RunExecutionRefV1(
                    schema_version=1,
                    execution_kind="START",
                    run_id=run_id,
                    langgraph_thread_id=workflow_key,
                    graph_profile=self._graph_profile,
                    graph_version=self._graph_version,
                    requested_mode=command.requested_mode,  # type: ignore[arg-type]
                    resume_target=None,
                ),
                checkpoint_id=None,
                checkpoint_generation=0,
                control_kind="NONE",
                control=None,
                control_payload_hash=None,
            )
        )

        unit_of_work.traces.add(
            TraceEventRecord(
                run_id=run_id,
                action_id=None,
                event_type="RUN_CREATED",
                status=initial_status.value,
                duration_ms=None,
                payload_json=dumps(
                    {
                        "command_id": command.command_id,
                        "selected_resource_ids": list(command.selected_resource_ids),
                        "selected_resources": [asdict(resource) for resource in command.selected_resources],
                        "workflow_key": workflow_key,
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
                run_id=run_id,
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
            run_id=run_id,
            conversation_id=command.conversation_id,
            run_status=initial_status.value,
            run_version=0,
            user_message_id=user_message_id,
            workflow_key=workflow_key,
            handoff_id=handoff_id,
            enqueued=True,
            request_replayed=False,
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
                run_id=receipt.aggregate_id or "",
                action_id=None,
                now_ms=self._now_ms(),
            )
            return StartRunResult(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                run_id=receipt.aggregate_id or "",
                conversation_id="",
                run_status="UNKNOWN",
                run_version=receipt.result_version or 0,
                user_message_id="",
                workflow_key="",
                handoff_id="",
                enqueued=False,
                request_replayed=True,
                conflict_detail="command_id already exists with a different request_hash",
            )

        self._validate_receipt_identity(receipt=receipt)

        if receipt.status is not CommandReceiptStatus.RECEIVED:
            if receipt.response_json is None:
                raise RuntimeError("completed StartRun receipt is missing replay response")
            response = StartRunResult(**loads(receipt.response_json))
            self._validate_replay_response(receipt=receipt, command=command, response=response)
            return StartRunResult(**{**asdict(response), "enqueued": False, "request_replayed": True})

        run_id = receipt.aggregate_id
        run = None if run_id is None else unit_of_work.runs.get(run_id)

        if run is None and run_id is not None:
            messages, _ = unit_of_work.messages.list_by_conversation_keyset(
                conversation_id=command.conversation_id,
                cursor=None,
                page_size=200,
            )
            if any(item.run_id == run_id for item in messages):
                raise RuntimeError("StartRun receipt recovery found USER Message without Run")

        if run is not None:
            if run.conversation_id != command.conversation_id:
                raise RuntimeError("StartRun receipt aggregate belongs to a different conversation")
            handoff = unit_of_work.workflow_handoffs.get_by_trigger_command_id(command.command_id)
            if handoff is None or handoff.execution.run_id != run.id:
                raise RuntimeError(
                    "StartRun receipt recovery found a Run without a matching WorkflowHandoff"
                )
            messages, _ = unit_of_work.messages.list_by_conversation_keyset(
                conversation_id=command.conversation_id,
                cursor=None,
                page_size=200,
            )
            message = next(
                (item for item in messages if item.run_id == run.id and item.role == "USER"),
                None,
            )
            if (
                message is None
                or message.conversation_id != command.conversation_id
                or message.content != command.request_text
            ):
                raise RuntimeError("StartRun receipt recovery found an incomplete aggregate mutation")

            self._validate_complete_aggregate_evidence(
                unit_of_work=unit_of_work,
                command=command,
                run_id=run.id,
                workflow_key=handoff.execution.langgraph_thread_id,
            )
            stored_response = StartRunResult(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                run_id=run.id,
                conversation_id=command.conversation_id,
                run_status=RunStatus.CREATED.value,
                run_version=0,
                user_message_id=message.id,
                workflow_key=handoff.execution.langgraph_thread_id,
                handoff_id=handoff.handoff_id,
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
            return StartRunResult(
                **{**asdict(stored_response), "enqueued": False, "request_replayed": True}
            )

        self._fail_closed_no_aggregate_recovery(
            unit_of_work=unit_of_work,
            command=command,
            run_id=run_id,
        )
        raise AssertionError("unreachable")

    @staticmethod
    def _validate_receipt_identity(*, receipt: CommandReceiptRecord) -> None:
        if receipt.command_type != "StartRun" or receipt.aggregate_type != "Run":
            raise RuntimeError("StartRun receipt identity does not match command")

    @staticmethod
    def _validate_replay_response(
        *,
        receipt: CommandReceiptRecord,
        command: StartRunCommand,
        response: StartRunResult,
    ) -> None:
        if response.conversation_id != command.conversation_id:
            raise RuntimeError("StartRun replay response identity does not match command")
        if receipt.result_code is not None and response.result_code != receipt.result_code.value:
            raise RuntimeError("StartRun replay response result does not match receipt")
        if receipt.result_version is not None and response.run_version != receipt.result_version:
            raise RuntimeError("StartRun replay response version does not match receipt")
        if receipt.status is CommandReceiptStatus.APPLIED and not response.applied:
            raise RuntimeError("StartRun replay response applied flag does not match receipt")
        if receipt.status is CommandReceiptStatus.REJECTED and response.applied:
            raise RuntimeError("StartRun replay response applied flag does not match receipt")

    def _validate_complete_aggregate_evidence(
        self,
        *,
        unit_of_work: UnitOfWork,
        command: StartRunCommand,
        run_id: str,
        workflow_key: str,
    ) -> None:
        audit_created = 0
        for event in self._list_all_audits(unit_of_work=unit_of_work, run_id=run_id):
            if event.event_type != "RUN_CREATED":
                continue
            audit_created += 1
            self._validate_run_created_audit(event=event, command=command)
        if audit_created > 1:
            raise RuntimeError("StartRun receipt recovery found duplicate RUN_CREATED Audit evidence")

        trace_created = 0
        for event in self._list_all_traces(unit_of_work=unit_of_work, run_id=run_id):
            if event.event_type != "RUN_CREATED":
                continue
            trace_created += 1
            self._validate_run_created_trace(event=event, command=command, workflow_key=workflow_key)
        if trace_created > 1:
            raise RuntimeError("StartRun receipt recovery found duplicate RUN_CREATED Trace evidence")

    def _fail_closed_no_aggregate_recovery(
        self,
        *,
        unit_of_work: UnitOfWork,
        command: StartRunCommand,
        run_id: str | None,
    ) -> None:
        if run_id is not None:
            for event in self._list_all_audits(unit_of_work=unit_of_work, run_id=run_id):
                payload = self._event_payload(event.metadata_json, evidence_kind="Audit")
                if event.event_type == "COMMAND_RECEIVED":
                    self._validate_command_received_event(
                        payload=payload,
                        command=command,
                        evidence_kind="Audit",
                    )
                    continue
                if event.event_type == "RUN_CREATED":
                    self._validate_run_created_audit(event=event, command=command)
                    raise RuntimeError(
                        "StartRun receipt recovery found prior RUN_CREATED Audit evidence without aggregate"
                    )
                if event.event_type == "COMMAND_APPLIED":
                    self._validate_command_event(
                        payload=payload,
                        command=command,
                        evidence_kind="Audit",
                        event_type="COMMAND_APPLIED",
                    )
                    raise RuntimeError(
                        "StartRun receipt recovery found prior COMMAND_APPLIED Audit evidence without aggregate"
                    )
                raise RuntimeError("StartRun receipt recovery found contradictory durable Audit evidence")

            for event in self._list_all_traces(unit_of_work=unit_of_work, run_id=run_id):
                payload = self._event_payload(event.payload_json, evidence_kind="Trace")
                if event.event_type == "COMMAND_RECEIVED":
                    self._validate_command_received_event(
                        payload=payload,
                        command=command,
                        evidence_kind="Trace",
                    )
                    continue
                if event.event_type == "RUN_CREATED":
                    self._validate_run_created_trace(
                        event=event, command=command, workflow_key=None
                    )
                    raise RuntimeError(
                        "StartRun receipt recovery found prior RUN_CREATED Trace evidence without aggregate"
                    )
                if event.event_type == "COMMAND_APPLIED":
                    self._validate_command_event(
                        payload=payload,
                        command=command,
                        evidence_kind="Trace",
                        event_type="COMMAND_APPLIED",
                    )
                    raise RuntimeError(
                        "StartRun receipt recovery found prior COMMAND_APPLIED Trace evidence without aggregate"
                    )
                raise RuntimeError("StartRun receipt recovery found contradictory durable Trace evidence")

        raise RuntimeError(
            "StartRun RECEIVED receipt has no canonical proof of non-application"
        )

    def _list_all_audits(
        self,
        *,
        unit_of_work: UnitOfWork,
        run_id: str,
    ) -> tuple[PersistedAuditEventRecord, ...]:
        collected: list[PersistedAuditEventRecord] = []
        cursor_after: int | None = None
        while True:
            batch = unit_of_work.audits.list_by_aggregate(
                run_id=run_id,
                action_id=None,
                cursor_after=cursor_after,
                limit=self._EVIDENCE_PAGE_SIZE,
            )
            if not batch:
                break
            collected.extend(batch)
            next_cursor = batch[-1].id
            if cursor_after is not None and next_cursor <= cursor_after:
                raise RuntimeError("StartRun Audit evidence cursor did not advance")
            cursor_after = next_cursor
            if len(batch) < self._EVIDENCE_PAGE_SIZE:
                break
        return tuple(collected)

    def _list_all_traces(
        self,
        *,
        unit_of_work: UnitOfWork,
        run_id: str,
    ) -> tuple[PersistedTraceEventRecord, ...]:
        collected: list[PersistedTraceEventRecord] = []
        cursor_after: int | None = None
        while True:
            batch = unit_of_work.traces.list_by_run_after_cursor(
                run_id=run_id,
                cursor_after=cursor_after,
                limit=self._EVIDENCE_PAGE_SIZE,
            )
            if not batch:
                break
            collected.extend(batch)
            next_cursor = batch[-1].id
            if cursor_after is not None and next_cursor <= cursor_after:
                raise RuntimeError("StartRun Trace evidence cursor did not advance")
            cursor_after = next_cursor
            if len(batch) < self._EVIDENCE_PAGE_SIZE:
                break
        return tuple(collected)

    @classmethod
    def _validate_run_created_audit(
        cls,
        *,
        event: PersistedAuditEventRecord,
        command: StartRunCommand,
    ) -> None:
        payload = cls._event_payload(event.metadata_json, evidence_kind="Audit")
        if (
            event.action_id is not None
            or event.outcome != ResultCode.TRANSITION_APPLIED.value
            or cls._event_field(payload, "command_id") != command.command_id
            or cls._event_field(payload, "conversation_id") != command.conversation_id
            or cls._event_field(payload, "entry_mode") != command.entry_mode
        ):
            raise RuntimeError("StartRun receipt recovery found conflicting RUN_CREATED Audit evidence")

    @classmethod
    def _validate_run_created_trace(
        cls,
        *,
        event: PersistedTraceEventRecord,
        command: StartRunCommand,
        workflow_key: str | None,
    ) -> None:
        payload = cls._event_payload(event.payload_json, evidence_kind="Trace")
        if (
            event.action_id is not None
            or event.status != RunStatus.CREATED.value
            or cls._event_field(payload, "command_id") != command.command_id
            or (workflow_key is not None and cls._event_field(payload, "workflow_key") != workflow_key)
            or cls._event_field(payload, "requested_mode") != command.requested_mode
            or cls._event_field(payload, "selected_resource_ids")
            != list(command.selected_resource_ids)
            or cls._event_field(payload, "selected_resources")
            != [asdict(resource) for resource in command.selected_resources]
        ):
            raise RuntimeError("StartRun receipt recovery found conflicting RUN_CREATED Trace evidence")

    @classmethod
    def _validate_command_received_event(
        cls,
        *,
        payload: dict[str, object],
        command: StartRunCommand,
        evidence_kind: str,
    ) -> None:
        cls._validate_command_event(
            payload=payload,
            command=command,
            evidence_kind=evidence_kind,
            event_type="COMMAND_RECEIVED",
        )

    @classmethod
    def _validate_command_event(
        cls,
        *,
        payload: dict[str, object],
        command: StartRunCommand,
        evidence_kind: str,
        event_type: str,
    ) -> None:
        command_type = cls._event_field(payload, "command_type")
        if (
            cls._event_field(payload, "command_id") != command.command_id
            or (command_type is not None and command_type != "StartRun")
        ):
            raise RuntimeError(
                f"StartRun receipt recovery found conflicting {event_type} {evidence_kind} evidence"
            )

    @staticmethod
    def _event_payload(raw_json: str, *, evidence_kind: str) -> dict[str, object]:
        try:
            payload = loads(raw_json)
        except (TypeError, ValueError) as error:
            raise RuntimeError(
                f"StartRun receipt recovery found malformed {evidence_kind} evidence"
            ) from error
        if not isinstance(payload, dict):
            raise RuntimeError(f"StartRun receipt recovery found malformed {evidence_kind} evidence")
        return payload

    @staticmethod
    def _event_field(payload: dict[str, object], field_name: str) -> object | None:
        attributes = payload.get("attributes")
        if isinstance(attributes, dict) and field_name in attributes:
            return attributes[field_name]
        correlation = payload.get("correlation")
        if isinstance(correlation, dict) and field_name in correlation:
            return correlation[field_name]
        return payload.get(field_name)

    @staticmethod
    def _open_run_conflict(
        *,
        run_id: str,
        conversation_id: str,
        user_message_id: str,
        workflow_key: str,
        current_open: object,
    ) -> StartRunResult:
        if current_open is None:
            run_status = RunStatus.CREATED.value
            run_version = 0
        else:
            run_status = current_open.status.value
            run_version = current_open.version
        return StartRunResult(
            applied=False,
            result_code=ResultCode.STATE_CONFLICT.value,
            run_id=run_id,
            conversation_id=conversation_id,
            run_status=run_status,
            run_version=run_version,
            user_message_id=user_message_id,
            workflow_key=workflow_key,
            handoff_id="",
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
