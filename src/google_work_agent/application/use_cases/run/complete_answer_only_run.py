"""Answer-only product core application flow."""

from collections.abc import Callable
from dataclasses import dataclass
from json import dumps

from google_work_agent.application.use_cases.run.build_terminal_message import (
    BuildTerminalMessageHandler,
    BuildTerminalMessageQueryV1,
)
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.command_receipt.model import (
    AnswerOnlyResponse,
    CommandReceiptStatus,
    DuplicateCommandError,
)
from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.message.model import Message as MessageRecord
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1, next_allowed_run_commands
from google_work_agent.domain.run.transitions.complete_answer_only_run import (
    transition_complete_answer_only_run,
)
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import UnitOfWork
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple


@dataclass(frozen=True, slots=True)
class CompleteAnswerOnlyRunCommand:
    """Input contract for the answer-only completion use case."""

    command_id: str
    conversation_id: str
    run_id: str
    assistant_message: str
    expected_version: int
    request_hash: str


class CompleteAnswerOnlyRunHandler:
    """Durably complete an answer-only run with command receipts."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        message_id_factory: Callable[[], str],
        build_terminal_message: BuildTerminalMessageHandler | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._message_id_factory = message_id_factory
        self._build_terminal_message = build_terminal_message or BuildTerminalMessageHandler()

    def __call__(self, command: CompleteAnswerOnlyRunCommand) -> AnswerOnlyResponse:
        """Complete the run or return the previously stored idempotent response."""
        terminal_message = self._build_terminal_message(
            BuildTerminalMessageQueryV1(
                run_id=command.run_id,
                result_kind="ANSWER",
                content=command.assistant_message,
            )
        )
        with self._unit_of_work_factory() as unit_of_work:
            existing_receipt = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing_receipt is not None:
                return self._handle_existing_receipt(unit_of_work, command, existing_receipt)

            now_ms = self._now_ms()
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="CompleteAnswerOnlyRun",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )

            conversation = unit_of_work.conversations.get(command.conversation_id)
            if conversation is None:
                raise LookupError(f"conversation not found: {command.conversation_id}")

            run = unit_of_work.runs.get(command.run_id)
            if run is None:
                raise LookupError(f"run not found: {command.run_id}")
            if run.conversation_id != conversation.id:
                raise LookupError(
                    "run "
                    f"{command.run_id} does not belong to conversation "
                    f"{command.conversation_id}"
                )

            if run.version != command.expected_version:
                response = AnswerOnlyResponse(
                    False,
                    ResultCode.VERSION_CONFLICT,
                    run.status,
                    run.version,
                    (),
                    "expected_version does not match current_version",
                )
            else:
                plans = current_plan_tuple(unit_of_work.plans, run.id)
                has_action = any(unit_of_work.actions.list_for_plan(plan.id) for plan in plans)
                next_status = transition_complete_answer_only_run(
                    run.status,
                    has_plan=bool(plans),
                    has_action=has_action,
                    has_open_write=False,
                    has_executing_read=False,
                    has_unresolved_recovery=False,
                )
                applied = unit_of_work.runs.update_if_version_and_status(
                    run.id,
                    run.version,
                    frozenset({run.status}),
                    {
                        "status": next_status.value,
                        "version": run.version + 1,
                        "finished_at_ms": now_ms,
                    },
                )
                if not applied:
                    raise RuntimeError("validated CompleteAnswerOnlyRun CAS failed")
                response = AnswerOnlyResponse(
                    True, ResultCode.TRANSITION_APPLIED, next_status, run.version + 1, ()
                )

            if response.applied:
                assistant_message_id = self._message_id_factory()
                unit_of_work.messages.append_terminal_assistant_message(
                    MessageRecord(
                        id=assistant_message_id,
                        conversation_id=command.conversation_id,
                        run_id=command.run_id,
                        role="ASSISTANT",
                        content=terminal_message.content,
                        created_at_ms=now_ms,
                    )
                )
                unit_of_work.traces.append(
                    TraceEventRecord(
                        run_id=command.run_id,
                        action_id=None,
                        event_type="COMMAND_APPLIED",
                        status=response.current_status.value,
                        duration_ms=None,
                        payload_json=dumps(
                            {
                                "command_id": command.command_id,
                                "command_type": "CompleteAnswerOnlyRun",
                                "message_id": assistant_message_id,
                                "mode": "ANSWER_ONLY",
                                "request_hash_prefix": command.request_hash[:12],
                            },
                            sort_keys=True,
                        ),
                        created_at_ms=now_ms,
                    )
                )
                unit_of_work.audits.append(
                    AuditEventRecord(
                        account_id=conversation.account_id,
                        run_id=command.run_id,
                        action_id=None,
                        actor_type="AGENT",
                        actor_id="complete_answer_only_run",
                        actor_display="AnswerOnlyService",
                        event_type="RUN_COMPLETED",
                        outcome=response.result_code.value,
                        metadata_json=dumps(
                            {
                                "command_id": command.command_id,
                                "message_id": assistant_message_id,
                                "completion_mode": "ANSWER_ONLY",
                                "mode": "ANSWER_ONLY",
                            },
                            sort_keys=True,
                        ),
                        created_at_ms=now_ms,
                    )
                )
                response = AnswerOnlyResponse(
                    applied=True,
                    result_code=response.result_code,
                    current_status=response.current_status,
                    current_version=response.current_version,
                    next_allowed_commands=response.next_allowed_commands,
                    conflict_detail=response.conflict_detail,
                    assistant_message_id=assistant_message_id,
                )

            unit_of_work.command_receipts.store_result(
                command_id=command.command_id,
                applied=response.applied,
                result_code=response.result_code,
                result_version=response.current_version,
                response_json=_response_json(response),
                completed_at_ms=now_ms,
            )
            unit_of_work.commit()
            return response

    def _handle_existing_receipt(
        self,
        unit_of_work: UnitOfWork,
        command: CompleteAnswerOnlyRunCommand,
        existing_receipt: CommandReceiptRecord,
    ) -> AnswerOnlyResponse:
        if existing_receipt.request_hash != command.request_hash:
            run = unit_of_work.runs.get(command.run_id)
            if run is None:
                raise DuplicateCommandError(command.command_id)
            return AnswerOnlyResponse(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND,
                current_status=run.status,
                current_version=run.version,
                next_allowed_commands=next_allowed_run_commands(run.status),
                conflict_detail="command_id already exists with a different request_hash",
            )

        if (
            existing_receipt.response is not None
            and existing_receipt.status is not CommandReceiptStatus.RECEIVED
        ):
            return existing_receipt.response

        return self._recover_pending_receipt(unit_of_work, command)

    def _recover_pending_receipt(
        self,
        unit_of_work: UnitOfWork,
        command: CompleteAnswerOnlyRunCommand,
    ) -> AnswerOnlyResponse:
        run = unit_of_work.runs.get(command.run_id)
        if run is None:
            raise LookupError(f"run not found during receipt recovery: {command.run_id}")

        if run.status is RunStatusV1.COMPLETED:
            expected_content = self._build_terminal_message(
                BuildTerminalMessageQueryV1(
                    run_id=command.run_id,
                    result_kind="ANSWER",
                    content=command.assistant_message,
                )
            ).content
            messages, _ = unit_of_work.messages.list_by_conversation_keyset(
                conversation_id=command.conversation_id,
                cursor=None,
                page_size=200,
            )
            message = next(
                (
                    item
                    for item in messages
                    if item.run_id == command.run_id
                    and item.role == "ASSISTANT"
                    and item.content == expected_content
                ),
                None,
            )
            if message is not None:
                response = AnswerOnlyResponse(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED,
                    current_status=run.status,
                    current_version=run.version,
                    next_allowed_commands=next_allowed_run_commands(run.status),
                    assistant_message_id=message.id,
                )
                unit_of_work.command_receipts.store_result(
                    command_id=command.command_id,
                    applied=response.applied,
                    result_code=response.result_code,
                    result_version=response.current_version,
                    response_json=_response_json(response),
                    completed_at_ms=self._now_ms(),
                )
                unit_of_work.commit()
                return response

        response = AnswerOnlyResponse(
            applied=False,
            result_code=ResultCode.STATE_CONFLICT,
            current_status=run.status,
            current_version=run.version,
            next_allowed_commands=next_allowed_run_commands(run.status),
            conflict_detail="receipt is pending and aggregate state is not safely recoverable",
        )
        unit_of_work.command_receipts.store_result(
            command_id=command.command_id,
            applied=response.applied,
            result_code=response.result_code,
            result_version=response.current_version,
            response_json=_response_json(response),
            completed_at_ms=self._now_ms(),
        )
        unit_of_work.commit()
        return response


CompleteAnswerOnlyRunResult = AnswerOnlyResponse


def _response_json(response: AnswerOnlyResponse) -> str:
    return dumps(
        {
            "applied": response.applied,
            "result_code": response.result_code.value,
            "current_status": response.current_status.value,
            "current_version": response.current_version,
            "next_allowed_commands": [item.value for item in response.next_allowed_commands],
            "conflict_detail": response.conflict_detail,
            "assistant_message_id": response.assistant_message_id,
        },
        sort_keys=True,
    )

__all__ = [
    "CompleteAnswerOnlyRunCommand",
    "CompleteAnswerOnlyRunResult",
    "CompleteAnswerOnlyRunHandler",
]
