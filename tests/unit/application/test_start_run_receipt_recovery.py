from __future__ import annotations

from dataclasses import asdict, replace
from json import dumps

import pytest

from google_work_agent.application.use_cases.run.start_run import (
    StartRunCommand,
    StartRunHandler,
    StartRunResult,
)
from google_work_agent.domain import ResultCode, RunStatus
from google_work_agent.ports.models import (
    AuditEventRecord,
    CommandReceiptRecord,
    CommandReceiptStatus,
    ConversationRecord,
    MessageRecord,
    PersistedAuditEventRecord,
    PersistedTraceEventRecord,
    RunRecord,
    TraceEventRecord,
)


class _AuditCollector:
    def __init__(self) -> None:
        self.items: list[AuditEventRecord] = []

    def add(self, item: AuditEventRecord) -> None:
        self.items.append(item)

    def list_by_aggregate(
        self,
        *,
        run_id: str | None,
        action_id: str | None = None,
        cursor_after: int | None = None,
        limit: int = 100,
    ) -> tuple[PersistedAuditEventRecord, ...]:
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

    def add(self, item: TraceEventRecord) -> None:
        self.items.append(item)

    def list_by_run_after_cursor(
        self,
        *,
        run_id: str,
        cursor_after: int | None,
        limit: int = 100,
    ) -> tuple[PersistedTraceEventRecord, ...]:
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
            if item.run_id == run_id and (cursor_after is None or index > cursor_after)
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

    def get_by_id(self, conversation_id: str) -> ConversationRecord | None:
        return self.record if conversation_id == self.record.id else None

    def touch(self, conversation_id: str, *, updated_at_ms: int) -> None:
        assert conversation_id == self.record.id
        self.touch_count += 1


class _RunRepo:
    def __init__(self) -> None:
        self.records: dict[str, RunRecord] = {}
        self.add_count = 0

    def get_by_id(self, run_id: str) -> RunRecord | None:
        return self.records.get(run_id)

    def get_open_by_conversation(self, conversation_id: str) -> RunRecord | None:
        return next(
            (
                record
                for record in self.records.values()
                if record.conversation_id == conversation_id and record.finished_at_ms is None
            ),
            None,
        )

    def add(self, run: object) -> None:
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

    def get_by_id(self, message_id: str) -> MessageRecord | None:
        return self.records.get(message_id)

    def add(self, message: MessageRecord) -> None:
        self.add_count += 1
        self.records[message.id] = message


class _ReceiptRepo:
    def __init__(self) -> None:
        self.record: CommandReceiptRecord | None = None
        self.add_received_count = 0
        self.finish_count = 0

    def get_by_command_id(self, command_id: str) -> CommandReceiptRecord | None:
        return self.record if self.record is not None and self.record.command_id == command_id else None

    def add_received(self, **kwargs: object) -> None:
        self.add_received_count += 1
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

    def finish_json(self, **kwargs: object) -> None:
        assert self.record is not None
        self.finish_count += 1
        self.record = replace(
            self.record,
            status=CommandReceiptStatus.APPLIED if kwargs["applied"] else CommandReceiptStatus.REJECTED,
            result_code=kwargs["result_code"],
            result_version=int(kwargs["result_version"]),
            response_json=str(kwargs["response_json"]),
            completed_at_ms=int(kwargs["completed_at_ms"]),
        )


class _UnitOfWork:
    def __init__(self) -> None:
        self.conversations = _ConversationRepo()
        self.runs = _RunRepo()
        self.messages = _MessageRepo()
        self.command_receipts = _ReceiptRepo()
        self.traces = _TraceCollector()
        self.audits = _AuditCollector()
        self.commit_count = 0

    def __enter__(self) -> "_UnitOfWork":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        return None


def _command(*, request_hash: str = "hash-1") -> StartRunCommand:
    return StartRunCommand(
        command_id="command-1",
        request_hash=request_hash,
        conversation_id="conversation-1",
        user_message_id="message-1",
        run_id="run-1",
        workflow_key="thread-1",
        request_text="hello",
        entry_mode="CHAT",
        selected_resource_ids=(),
        requested_mode="AUTO",
        api_contract_version="v1",
    )


def _received(command: StartRunCommand) -> CommandReceiptRecord:
    return CommandReceiptRecord(
        command_id=command.command_id,
        command_type="StartRun",
        request_hash=command.request_hash,
        aggregate_type="Run",
        aggregate_id=command.run_id,
        status=CommandReceiptStatus.RECEIVED,
        result_code=None,
        result_version=None,
        response=None,
        response_json=None,
        created_at_ms=10,
        completed_at_ms=None,
    )


def _stored_success(command: StartRunCommand) -> StartRunResult:
    return StartRunResult(
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


def _run_created_audit(
    command: StartRunCommand,
    *,
    command_id: str | None = None,
) -> AuditEventRecord:
    return AuditEventRecord(
        account_id="account-1",
        run_id=command.run_id,
        action_id=None,
        actor_type="USER",
        actor_id="account-1",
        actor_display=None,
        event_type="RUN_CREATED",
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
    command_id: str | None = None,
) -> TraceEventRecord:
    return TraceEventRecord(
        run_id=command.run_id,
        action_id=None,
        event_type="RUN_CREATED",
        status=RunStatus.CREATED.value,
        duration_ms=None,
        payload_json=dumps(
            {
                "command_id": command.command_id if command_id is None else command_id,
                "selected_resource_ids": list(command.selected_resource_ids),
                "selected_resources": [asdict(resource) for resource in command.selected_resources],
                "workflow_key": command.workflow_key,
                "requested_mode": command.requested_mode,
            },
            sort_keys=True,
        ),
        created_at_ms=10,
    )


def _command_received_audit(command: StartRunCommand) -> AuditEventRecord:
    return AuditEventRecord(
        account_id="account-1",
        run_id=command.run_id,
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
                "aggregate_id": command.run_id,
            },
            sort_keys=True,
        ),
        created_at_ms=10,
    )


def _command_applied_audit(command: StartRunCommand) -> AuditEventRecord:
    return AuditEventRecord(
        account_id="account-1",
        run_id=command.run_id,
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
                "aggregate_id": command.run_id,
            },
            sort_keys=True,
        ),
        created_at_ms=10,
    )


def _handler(uow: _UnitOfWork) -> StartRunHandler:
    return StartRunHandler(unit_of_work_factory=lambda: uow, now_ms=lambda: 20)


def test_fresh_start_run_persists_one_run_one_user_message_and_receipt() -> None:
    uow = _UnitOfWork()
    result = _handler(uow)(_command())

    assert result.applied is True
    assert result.request_replayed is False
    assert uow.runs.add_count == 1
    assert uow.messages.add_count == 1
    assert len(uow.traces.items) == 1
    assert len(uow.audits.items) == 1
    assert uow.command_receipts.add_received_count == 1
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
    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.traces.items) == 0
    assert len(uow.audits.items) == 0


@pytest.mark.parametrize(
    ("field_name", "wrong_value"),
    (
        ("command_type", "ApproveAction"),
        ("aggregate_type", "Action"),
        ("aggregate_id", "other-run"),
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
    uow.runs.records[command.run_id] = RunRecord(
        id=command.run_id,
        conversation_id=command.conversation_id,
        status=RunStatus.ANALYZING,
        version=1,
        started_at_ms=10,
        finished_at_ms=None,
    )
    uow.messages.records[command.user_message_id] = MessageRecord(
        id=command.user_message_id,
        conversation_id=command.conversation_id,
        run_id=command.run_id,
        role="USER",
        content=command.request_text,
        created_at_ms=10,
    )
    uow.audits.add(_run_created_audit(command))
    uow.traces.add(_run_created_trace(command))

    result = _handler(uow)(command)

    assert result.applied is True
    assert result.run_status == RunStatus.CREATED.value
    assert result.run_version == 0
    assert result.enqueued is False
    assert result.request_replayed is True
    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
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
    assert uow.command_receipts.add_received_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.traces.items) == 0
    assert len(uow.audits.items) == 0


def test_received_receipt_without_aggregate_with_command_received_only_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    uow.audits.add(_command_received_audit(command))

    with pytest.raises(RuntimeError, match="no canonical proof of non-application"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.add_received_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.audits.items) == 1
    assert len(uow.traces.items) == 0


def test_received_receipt_without_aggregate_with_prior_run_created_audit_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    uow.audits.add(_run_created_audit(command))

    with pytest.raises(RuntimeError, match="prior RUN_CREATED Audit evidence without aggregate"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.add_received_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.audits.items) == 1
    assert len(uow.traces.items) == 0


def test_received_receipt_without_aggregate_with_prior_run_created_trace_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    uow.traces.add(_run_created_trace(command))

    with pytest.raises(RuntimeError, match="prior RUN_CREATED Trace evidence without aggregate"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.add_received_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.audits.items) == 0
    assert len(uow.traces.items) == 1


def test_received_receipt_without_aggregate_with_command_applied_audit_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    uow.audits.add(_command_applied_audit(command))

    with pytest.raises(RuntimeError, match="prior COMMAND_APPLIED Audit evidence without aggregate"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.add_received_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.audits.items) == 1
    assert len(uow.traces.items) == 0


def test_received_receipt_without_aggregate_with_conflicting_run_created_audit_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    uow.audits.add(_run_created_audit(command, command_id="other-command"))

    with pytest.raises(RuntimeError, match="conflicting RUN_CREATED Audit evidence"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.audits.items) == 1
    assert len(uow.traces.items) == 0


def test_received_receipt_without_aggregate_old_receipt_still_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = replace(_received(command), created_at_ms=0)
    handler = StartRunHandler(
        unit_of_work_factory=lambda: uow,
        now_ms=lambda: 10**15,
    )

    with pytest.raises(RuntimeError, match="no canonical proof of non-application"):
        handler(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.add_received_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.audits.items) == 0
    assert len(uow.traces.items) == 0


def test_received_receipt_with_duplicate_run_created_audit_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    uow.runs.records[command.run_id] = RunRecord(
        id=command.run_id,
        conversation_id=command.conversation_id,
        status=RunStatus.CREATED,
        version=0,
        started_at_ms=10,
        finished_at_ms=None,
    )
    uow.messages.records[command.user_message_id] = MessageRecord(
        id=command.user_message_id,
        conversation_id=command.conversation_id,
        run_id=command.run_id,
        role="USER",
        content=command.request_text,
        created_at_ms=10,
    )
    uow.audits.add(_run_created_audit(command))
    uow.audits.add(_run_created_audit(command))
    uow.traces.add(_run_created_trace(command))

    with pytest.raises(RuntimeError, match="duplicate RUN_CREATED Audit evidence"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.finish_count == 0
    assert len(uow.audits.items) == 2
    assert len(uow.traces.items) == 1


def test_received_receipt_with_partial_aggregate_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    uow.runs.records[command.run_id] = RunRecord(
        id=command.run_id,
        conversation_id=command.conversation_id,
        status=RunStatus.CREATED,
        version=0,
        started_at_ms=10,
        finished_at_ms=None,
    )

    with pytest.raises(RuntimeError, match="incomplete aggregate mutation"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.finish_count == 0


def test_received_receipt_with_message_only_partial_aggregate_fails_closed() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = _received(command)
    uow.messages.records[command.user_message_id] = MessageRecord(
        id=command.user_message_id,
        conversation_id=command.conversation_id,
        run_id=command.run_id,
        role="USER",
        content=command.request_text,
        created_at_ms=10,
    )

    with pytest.raises(RuntimeError, match="USER Message without Run"):
        _handler(uow)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.finish_count == 0
