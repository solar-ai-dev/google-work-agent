from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import asdict, replace
from json import dumps

import pytest

from google_work_agent.application.use_cases.run.start_run import (
    StartRunCommand,
    StartRunHandler,
    StartRunResult,
)
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.conversation.model import Conversation as ConversationRecord
from google_work_agent.domain.message.model import Message as MessageRecord
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import Run as RunRecord
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.persistence.audit_event_repository import (
    AuditEventCursor,
    PersistedAuditEventRecord,
)
from google_work_agent.ports.persistence.trace_event_repository import (
    PersistedTraceEventRecord,
    TraceEventCursor,
)
from google_work_agent.ports.system.contracts.workflow_binding import WorkflowBindingV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionRefV1,
    WorkflowHandoffStageV1,
    WorkflowHandoffV1,
)


class _AuditCollector:
    def __init__(self) -> None:
        self.items: list[AuditEventRecord] = []

    def append(self, item: AuditEventRecord) -> None:
        self.items.append(item)

    def list_page(
        self, cursor: AuditEventCursor | None, limit: int
    ) -> tuple[PersistedAuditEventRecord, ...]:
        run_id = None if cursor is None else cursor.run_id
        action_id = None if cursor is None else cursor.action_id
        cursor_after = None if cursor is None else cursor.after_id
        records = tuple(
            PersistedAuditEventRecord(
                id=index,
                account_id=item.account_id,
                run_id=item.run_id,
                action_id=item.action_id,
                actor_type=item.actor_type,
                actor_id=item.actor_id,
                actor_display=item.actor_display,
                event_type=item.event_type,
                outcome=item.outcome,
                metadata_json=item.metadata_json,
                created_at_ms=item.created_at_ms,
            )
            for index, item in enumerate(self.items, start=1)
            if (run_id is None or item.run_id == run_id)
            and (action_id is None or item.action_id == action_id)
            and (cursor_after is None or index > cursor_after)
        )
        return records[:limit]


class _TraceCollector:
    def __init__(self) -> None:
        self.items: list[TraceEventRecord] = []

    def append(self, item: TraceEventRecord) -> None:
        self.items.append(item)

    def list_page(
        self, cursor: TraceEventCursor | None, limit: int
    ) -> tuple[PersistedTraceEventRecord, ...]:
        run_id = None if cursor is None else cursor.run_id
        cursor_after = None if cursor is None else cursor.after_id
        records = tuple(
            PersistedTraceEventRecord(
                id=index,
                run_id=item.run_id,
                action_id=item.action_id,
                event_type=item.event_type,
                status=item.status,
                duration_ms=item.duration_ms,
                payload_json=item.payload_json,
                created_at_ms=item.created_at_ms,
            )
            for index, item in enumerate(self.items, start=1)
            if (run_id is None or item.run_id == run_id)
            and (cursor_after is None or index > cursor_after)
        )
        return records[:limit]


class _ConversationRepo:
    def __init__(self) -> None:
        self.record = ConversationRecord(
            id="conversation-1",
            account_id="account-1",
            title="title",
            created_at_ms=1,
            updated_at_ms=1,
        )
        self.touch_count = 0

    def get(self, conversation_id: str) -> ConversationRecord | None:
        return self.record if conversation_id == self.record.id else None

    def touch_updated_at(self, conversation_id: str, *, updated_at_ms: int) -> None:
        assert conversation_id == self.record.id
        self.touch_count += 1


class _RunRepo:
    def __init__(self) -> None:
        self.records: dict[str, RunRecord] = {}
        self.add_count = 0

    def get(self, run_id: str) -> RunRecord | None:
        return self.records.get(run_id)

    def find_open_by_conversation(self, conversation_id: str) -> RunRecord | None:
        return next(
            (
                record
                for record in self.records.values()
                if record.conversation_id == conversation_id and record.finished_at_ms is None
            ),
            None,
        )

    def create(self, run: object) -> None:
        self.add_count += 1
        self.records[run.id] = RunRecord(
            id=run.id,
            conversation_id=run.conversation_id,
            status=run.status,
            version=run.version,
            started_at_ms=run.started_at_ms,
            finished_at_ms=run.finished_at_ms,
        )


class _MessageRepo:
    def __init__(self) -> None:
        self.records: dict[str, MessageRecord] = {}
        self.add_count = 0

    def append_user_message(self, message: MessageRecord) -> None:
        self.add_count += 1
        self.records[message.id] = message

    def list_by_conversation_keyset(
        self, *, conversation_id: str, cursor: str | None, page_size: int
    ) -> tuple[tuple[MessageRecord, ...], str | None]:
        del cursor
        records = tuple(
            record
            for record in reversed(tuple(self.records.values()))
            if record.conversation_id == conversation_id
        )
        return records[:page_size], None


class _ReceiptRepo:
    def __init__(self) -> None:
        self.record: CommandReceiptRecord | None = None
        self.reserve_count = 0
        self.finish_count = 0

    def get_by_command_id(self, command_id: str) -> CommandReceiptRecord | None:
        return (
            self.record
            if self.record is not None and self.record.command_id == command_id
            else None
        )

    def reserve_or_replay(self, **kwargs: object) -> CommandReceiptRecord | None:
        if self.record is not None:
            return self.record
        self.reserve_count += 1
        self.record = CommandReceiptRecord(
            command_id=str(kwargs["command_id"]),
            command_type=str(kwargs["command_type"]),
            request_hash=str(kwargs["request_hash"]),
            aggregate_type=str(kwargs["aggregate_type"]),
            aggregate_id=None if kwargs["aggregate_id"] is None else str(kwargs["aggregate_id"]),
            status=CommandReceiptStatus.RECEIVED,
            result_code=None,
            result_version=None,
            response=None,
            response_json=None,
            created_at_ms=int(kwargs["created_at_ms"]),
            completed_at_ms=None,
        )
        return None

    def store_result(self, **kwargs: object) -> None:
        assert self.record is not None
        self.finish_count += 1
        self.record = replace(
            self.record,
            status=CommandReceiptStatus.APPLIED
            if kwargs["applied"]
            else CommandReceiptStatus.REJECTED,
            result_code=kwargs["result_code"],
            result_version=int(kwargs["result_version"]),
            response_json=str(kwargs["response_json"]),
            completed_at_ms=int(kwargs["completed_at_ms"]),
        )


class _WorkflowHandoffRepo:
    def __init__(self) -> None:
        self.records: dict[str, WorkflowHandoffV1] = {}
        self.stage_count = 0

    def stage_pending(self, stage: WorkflowHandoffStageV1) -> WorkflowHandoffV1:
        self.stage_count += 1
        handoff = WorkflowHandoffV1(
            schema_version=1,
            handoff_id=stage.handoff_id,
            trigger_command_id=stage.trigger_command_id,
            execution=stage.execution,
            checkpoint_id=stage.checkpoint_id,
            checkpoint_generation=stage.checkpoint_generation,
            run_sequence=1,
            control_kind=stage.control_kind,
            control=stage.control,
            control_payload_hash=stage.control_payload_hash,
            status="PENDING",
            last_submit_reason=None,
            execution_admission=None,
            applied_checkpoint_id=None,
            applied_checkpoint_generation=None,
            version=0,
        )
        self.records[stage.handoff_id] = handoff
        return handoff

    def get(self, handoff_id: str) -> WorkflowHandoffV1 | None:
        return self.records.get(handoff_id)

    def get_by_trigger_command_id(self, trigger_command_id: str) -> WorkflowHandoffV1 | None:
        return next(
            (
                item
                for item in self.records.values()
                if item.trigger_command_id == trigger_command_id
            ),
            None,
        )


class _ResourceRefRepo:
    def __init__(self) -> None:
        self.records: dict[str, object] = {}

    def upsert_bound_ref(self, record: object) -> object:
        self.records[record.id] = record  # type: ignore[attr-defined]
        return record


class _CheckpointPort:
    def __init__(self) -> None:
        self.bindings: dict[str, WorkflowBindingV1] = {}

    def create_workflow_binding(self, binding: WorkflowBindingV1) -> None:
        existing = self.bindings.get(binding.run_id)
        if existing is not None and existing != binding:
            raise RuntimeError("conflicting binding")
        self.bindings[binding.run_id] = binding

    def load_workflow_binding(self, run_id: str) -> WorkflowBindingV1 | None:
        return self.bindings.get(run_id)


class _UnitOfWork:
    def __init__(self) -> None:
        self.conversations = _ConversationRepo()
        self.runs = _RunRepo()
        self.messages = _MessageRepo()
        self.command_receipts = _ReceiptRepo()
        self.traces = _TraceCollector()
        self.audits = _AuditCollector()
        self.workflow_handoffs = _WorkflowHandoffRepo()
        self.resource_refs = _ResourceRefRepo()
        self.checkpoints = _CheckpointPort()
        self.commit_count = 0

    def __enter__(self) -> _UnitOfWork:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        return None


def _id_factory(*, start: int = 1) -> Callable[[], str]:
    counter = itertools.count(start)
    return lambda: f"id-{next(counter)}"


def _command(*, request_hash: str = "hash-1") -> StartRunCommand:
    return StartRunCommand(
        command_id="command-1",
        request_hash=request_hash,
        conversation_id="conversation-1",
        request_text="hello",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        api_contract_version="v1",
    )


def _received(command: StartRunCommand, *, run_id: str = "run-1") -> CommandReceiptRecord:
    return CommandReceiptRecord(
        command_id=command.command_id,
        command_type="StartRun",
        request_hash=command.request_hash,
        aggregate_type="Run",
        aggregate_id=run_id,
        status=CommandReceiptStatus.RECEIVED,
        result_code=None,
        result_version=None,
        response=None,
        response_json=None,
        created_at_ms=10,
        completed_at_ms=None,
    )


def _stored_success(
    command: StartRunCommand,
    *,
    run_id: str = "run-1",
    user_message_id: str = "message-1",
    workflow_key: str = "thread-1",
    handoff_id: str = "handoff-1",
) -> StartRunResult:
    return StartRunResult(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED.value,
        run_id=run_id,
        conversation_id=command.conversation_id,
        run_status=RunStatusV1.CREATED.value,
        run_version=0,
        user_message_id=user_message_id,
        workflow_key=workflow_key,
        handoff_id=handoff_id,
        enqueued=True,
        request_replayed=False,
    )


def _run_created_audit(
    command: StartRunCommand,
    *,
    run_id: str = "run-1",
    command_id: str | None = None,
) -> AuditEventRecord:
    return AuditEventRecord(
        account_id="account-1",
        run_id=run_id,
        action_id=None,
        actor_type="USER",
        actor_id="account-1",
        actor_display=None,
        event_type="RUN_STARTED",
        outcome=ResultCode.TRANSITION_APPLIED.value,
        metadata_json=dumps(
            {
                "command_id": command.command_id if command_id is None else command_id,
                "conversation_id": command.conversation_id,
                "entry_mode": command.entry_mode,
            },
            sort_keys=True,
        ),
        created_at_ms=10,
    )


def _run_created_trace(
    command: StartRunCommand,
    *,
    run_id: str = "run-1",
    workflow_key: str = "thread-1",
    command_id: str | None = None,
) -> TraceEventRecord:
    return TraceEventRecord(
        run_id=run_id,
        action_id=None,
        event_type="RUN_CREATED",
        status=RunStatusV1.CREATED.value,
        duration_ms=None,
        payload_json=dumps(
            {
                "command_id": command.command_id if command_id is None else command_id,
                "selected_resource_ids": [
                    item.resource_id for item in command.resolved_resource_selections
                ],
                "selected_resources": [],
                "workflow_key": workflow_key,
                "requested_mode": command.requested_mode,
            },
            sort_keys=True,
        ),
        created_at_ms=10,
    )


def _command_received_audit(command: StartRunCommand, *, run_id: str = "run-1") -> AuditEventRecord:
    return AuditEventRecord(
        account_id="account-1",
        run_id=run_id,
        action_id=None,
        actor_type="SYSTEM",
        actor_id="command_receipt",
        actor_display="CommandReceipt",
        event_type="COMMAND_RECEIVED",
        outcome="",
        metadata_json=dumps(
            {
                "command_id": command.command_id,
                "command_type": "StartRun",
                "aggregate_id": run_id,
            },
            sort_keys=True,
        ),
        created_at_ms=10,
    )


def _command_applied_audit(command: StartRunCommand, *, run_id: str = "run-1") -> AuditEventRecord:
    return AuditEventRecord(
        account_id="account-1",
        run_id=run_id,
        action_id=None,
        actor_type="SYSTEM",
        actor_id="command_receipt",
        actor_display="CommandReceipt",
        event_type="COMMAND_APPLIED",
        outcome=ResultCode.TRANSITION_APPLIED.value,
        metadata_json=dumps(
            {
                "command_id": command.command_id,
                "command_type": "StartRun",
                "aggregate_id": run_id,
            },
            sort_keys=True,
        ),
        created_at_ms=10,
    )


def _seed_complete_aggregate(
    uow: _UnitOfWork,
    command: StartRunCommand,
    *,
    run_id: str = "run-1",
    user_message_id: str = "message-1",
    workflow_key: str = "thread-1",
    handoff_id: str = "handoff-1",
) -> None:
    uow.runs.records[run_id] = RunRecord(
        id=run_id,
        conversation_id=command.conversation_id,
        status=RunStatusV1.ANALYZING,
        version=1,
        started_at_ms=10,
        finished_at_ms=None,
    )
    uow.messages.records[user_message_id] = MessageRecord(
        id=user_message_id,
        conversation_id=command.conversation_id,
        run_id=run_id,
        role="USER",
        content=command.request_text,
        created_at_ms=10,
    )
    uow.workflow_handoffs.records[handoff_id] = WorkflowHandoffV1(
        schema_version=1,
        handoff_id=handoff_id,
        trigger_command_id=command.command_id,
        execution=RunExecutionRefV1(
            schema_version=1,
            execution_kind="START",
            run_id=run_id,
            langgraph_thread_id=workflow_key,
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="resume-contract-v1",
            requested_mode="AUTO",
            resume_target=None,
        ),
        checkpoint_id=None,
        checkpoint_generation=0,
        run_sequence=1,
        control_kind="NONE",
        control=None,
        control_payload_hash=None,
        status="PENDING",
        last_submit_reason=None,
        execution_admission=None,
        applied_checkpoint_id=None,
        applied_checkpoint_generation=None,
        version=0,
    )
    uow.checkpoints.create_workflow_binding(
        WorkflowBindingV1(
            schema_version=1,
            workflow_key=workflow_key,
            run_id=run_id,
            langgraph_thread_id=workflow_key,
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="resume-contract-v1",
            requested_mode="AUTO",
            created_at_ms=10,
        )
    )


def _handler(uow: _UnitOfWork) -> StartRunHandler:
    return StartRunHandler(
        unit_of_work_factory=lambda: uow,
        now_ms=lambda: 20,
        id_factory=_id_factory(),
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="resume-contract-v1",
    )


def test_fresh_start_run_persists_one_run_one_user_message_and_receipt() -> None:
    uow = _UnitOfWork()
    result = _handler(uow)(_command())

    assert result.applied is True
    assert result.request_replayed is False
    assert result.handoff_id != ""
    assert uow.runs.add_count == 1
    assert uow.messages.add_count == 1
    assert uow.workflow_handoffs.stage_count == 1
    assert len(uow.checkpoints.bindings) == 1
    assert len(uow.traces.items) == 1
    assert len(uow.audits.items) == 1
    assert uow.command_receipts.reserve_count == 1
    assert uow.command_receipts.finish_count == 1
    assert uow.commit_count == 1


def test_completed_receipt_replays_without_duplicate_side_effects() -> None:
    uow = _UnitOfWork()
    command = _command()
    stored = _stored_success(command)
    uow.command_receipts.record = replace(
        _received(command),
        status=CommandReceiptStatus.APPLIED,
        result_code=ResultCode.TRANSITION_APPLIED,
        result_version=0,
        response_json=dumps(asdict(stored), sort_keys=True),
        completed_at_ms=15,
    )

    result = _handler(uow)(command)

    assert result.applied is True
    assert result.enqueued is False
    assert result.request_replayed is True
    assert result.handoff_id == stored.handoff_id
    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.workflow_handoffs.stage_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.traces.items) == 0
    assert len(uow.audits.items) == 0


@pytest.mark.parametrize(
    ("field_name", "wrong_value"),
    (
        ("command_type", "ApproveAction"),
        ("aggregate_type", "Action"),
    ),
)
def test_completed_receipt_with_wrong_identity_fails_closed_before_replay(
    field_name: str,
    wrong_value: str,
) -> None:
    uow = _UnitOfWork()
    command = _command()
    stored = _stored_success(command)
    receipt = replace(
        _received(command),
        status=CommandReceiptStatus.APPLIED,
        result_code=ResultCode.TRANSITION_APPLIED,
        result_version=0,
        response_json=dumps(asdict(stored), sort_keys=True),
        completed_at_ms=15,
    )
    uow.command_receipts.record = replace(receipt, **{field_name: wrong_value})

    with pytest.raises(RuntimeError, match="receipt identity does not match"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.traces.items) == 0
    assert len(uow.audits.items) == 0


def test_received_receipt_with_applied_aggregate_finishes_receipt_without_duplicates() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    _seed_complete_aggregate(uow, command)
    uow.audits.append(_run_created_audit(command))
    uow.traces.append(_run_created_trace(command))

    result = _handler(uow)(command)

    assert result.applied is True
    assert result.run_status == RunStatusV1.CREATED.value
    assert result.run_version == 0
    assert result.enqueued is False
    assert result.request_replayed is True
    assert result.handoff_id == "handoff-1"
    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.workflow_handoffs.stage_count == 0
    assert uow.command_receipts.finish_count == 1
    assert uow.commit_count == 1
    assert len(uow.traces.items) == 1
    assert len(uow.audits.items) == 1


def test_received_receipt_without_aggregate_and_without_prior_evidence_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)

    with pytest.raises(RuntimeError, match="no canonical proof of non-application"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.reserve_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.traces.items) == 0
    assert len(uow.audits.items) == 0
    assert uow.commit_count == 0


def test_received_receipt_without_aggregate_command_received_only_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    uow.audits.append(_command_received_audit(command))

    with pytest.raises(RuntimeError, match="no canonical proof of non-application"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.reserve_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.audits.items) == 1
    assert len(uow.traces.items) == 0
    assert uow.commit_count == 0


def test_received_receipt_without_aggregate_with_prior_run_created_audit_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    uow.audits.append(_run_created_audit(command))

    with pytest.raises(RuntimeError, match="prior RUN_STARTED Audit evidence without aggregate"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.reserve_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.audits.items) == 1
    assert len(uow.traces.items) == 0


def test_received_receipt_without_aggregate_with_prior_command_applied_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    uow.audits.append(_command_applied_audit(command))

    with pytest.raises(
        RuntimeError, match="prior COMMAND_APPLIED Audit evidence without aggregate"
    ):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.reserve_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.audits.items) == 1
    assert len(uow.traces.items) == 0


def test_received_receipt_without_aggregate_with_prior_run_created_trace_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    uow.traces.append(_run_created_trace(command))

    with pytest.raises(RuntimeError, match="prior RUN_CREATED Trace evidence without aggregate"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.reserve_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.audits.items) == 0
    assert len(uow.traces.items) == 1


def test_received_receipt_without_aggregate_with_conflicting_run_created_audit_fails_closed() -> (
    None
):
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    uow.audits.append(_run_created_audit(command, command_id="other-command"))

    with pytest.raises(RuntimeError, match="conflicting RUN_STARTED Audit evidence"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.audits.items) == 1
    assert len(uow.traces.items) == 0


def test_received_receipt_age_never_turns_absence_into_unapplied_proof() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = replace(_received(command), created_at_ms=0)
    handler = StartRunHandler(
        unit_of_work_factory=lambda: uow,
        now_ms=lambda: 10**15,
        id_factory=_id_factory(),
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="resume-contract-v1",
    )

    with pytest.raises(RuntimeError, match="no canonical proof of non-application"):
        handler(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.reserve_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.audits.items) == 0
    assert len(uow.traces.items) == 0


def test_received_receipt_with_duplicate_run_created_audit_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    _seed_complete_aggregate(uow, command)
    uow.audits.append(_run_created_audit(command))
    uow.audits.append(_run_created_audit(command))
    uow.traces.append(_run_created_trace(command))

    with pytest.raises(RuntimeError, match="duplicate RUN_STARTED Audit evidence"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.audits.items) == 2
    assert len(uow.traces.items) == 1
    assert uow.commit_count == 0


def test_received_receipt_with_partial_aggregate_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    uow.runs.records["run-1"] = RunRecord(
        id="run-1",
        conversation_id=command.conversation_id,
        status=RunStatusV1.CREATED,
        version=0,
        started_at_ms=10,
        finished_at_ms=None,
    )

    with pytest.raises(RuntimeError, match="matching WorkflowHandoff"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.finish_count == 0


def test_received_receipt_with_run_and_handoff_but_no_message_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    uow.runs.records["run-1"] = RunRecord(
        id="run-1",
        conversation_id=command.conversation_id,
        status=RunStatusV1.CREATED,
        version=0,
        started_at_ms=10,
        finished_at_ms=None,
    )
    uow.workflow_handoffs.records["handoff-1"] = WorkflowHandoffV1(
        schema_version=1,
        handoff_id="handoff-1",
        trigger_command_id=command.command_id,
        execution=RunExecutionRefV1(
            schema_version=1,
            execution_kind="START",
            run_id="run-1",
            langgraph_thread_id="thread-1",
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="resume-contract-v1",
            requested_mode="AUTO",
            resume_target=None,
        ),
        checkpoint_id=None,
        checkpoint_generation=0,
        run_sequence=1,
        control_kind="NONE",
        control=None,
        control_payload_hash=None,
        status="PENDING",
        last_submit_reason=None,
        execution_admission=None,
        applied_checkpoint_id=None,
        applied_checkpoint_generation=None,
        version=0,
    )

    with pytest.raises(RuntimeError, match="incomplete aggregate mutation"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0


def test_received_receipt_with_message_only_partial_aggregate_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    uow.messages.records["message-1"] = MessageRecord(
        id="message-1",
        conversation_id=command.conversation_id,
        run_id="run-1",
        role="USER",
        content=command.request_text,
        created_at_ms=10,
    )

    with pytest.raises(RuntimeError, match="USER Message without Run"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.finish_count == 0
    assert uow.command_receipts.finish_count == 0
