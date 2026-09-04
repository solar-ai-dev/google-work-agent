"""Answer-only product core application flow."""

from collections.abc import Callable
from dataclasses import dataclass
from json import dumps, loads
from typing import Literal, cast

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceDraftV1,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.plan.persistence_projection import current_plan_tuple
from google_work_agent.application.use_cases.resource_ref.persist_resource_ref import (
    persist_registered_resource_ref,
)
from google_work_agent.application.use_cases.run.build_terminal_message import (
    BuildTerminalMessageHandler,
    BuildTerminalMessageQueryV1,
)
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.command_receipt.model import (
    CommandReceiptStatus,
    DuplicateCommandError,
)
from google_work_agent.domain.evidence.model import Evidence as EvidenceRecord
from google_work_agent.domain.evidence.model import EvidenceOriginType
from google_work_agent.domain.message.model import Message as MessageRecord
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunCommand, RunStatusV1, next_allowed_run_commands
from google_work_agent.domain.run.transitions.complete_answer_only_run import (
    transition_complete_answer_only_run,
)
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class CompleteAnswerOnlyRunCommand:
    """Input contract for the answer-only completion use case."""

    command_id: str
    conversation_id: str
    run_id: str
    assistant_message: str
    expected_version: int
    request_hash: str
    result_kind: Literal["SUCCESS", "PARTIAL"] = "SUCCESS"
    retrieval_artifact_id: str | None = None
    evidence_drafts: tuple[EvidenceDraftV1, ...] = ()
    resource_ref_drafts: tuple[ResourceRefRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class CompleteAnswerOnlyRunResult:
    applied: bool
    result_code: ResultCode
    current_status: RunStatusV1
    current_version: int
    next_allowed_commands: tuple[RunCommand, ...]
    conflict_detail: str | None = None
    assistant_message_id: str | None = None
    result_kind: Literal["SUCCESS", "PARTIAL"] | None = None


class CompleteAnswerOnlyRunHandler:
    """Durably complete an answer-only run with command receipts."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        message_id_factory: Callable[[], str],
        evidence_id_factory: Callable[[], str] | None = None,
        tool_registry: SignedToolRegistry | None = None,
        build_terminal_message: BuildTerminalMessageHandler | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._message_id_factory = message_id_factory
        self._evidence_id_factory = evidence_id_factory or message_id_factory
        self._tool_registry = tool_registry
        self._build_terminal_message = build_terminal_message or BuildTerminalMessageHandler()

    def __call__(self, command: CompleteAnswerOnlyRunCommand) -> CompleteAnswerOnlyRunResult:
        """Complete the run or return the previously stored idempotent response."""
        terminal_message = self._build_terminal_message(
            BuildTerminalMessageQueryV1(
                schema_version=1,
                run_id=command.run_id,
                expected_run_version=command.expected_version,
                source_kind="ANSWER_DRAFT",
                result_kind=command.result_kind,
                answer_text=command.assistant_message,
                reason_codes=[],
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
                response = CompleteAnswerOnlyRunResult(
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
                        "terminal_result_kind": command.result_kind,
                    },
                )
                if not applied:
                    raise RuntimeError("validated CompleteAnswerOnlyRun CAS failed")
                response = CompleteAnswerOnlyRunResult(
                    True,
                    ResultCode.TRANSITION_APPLIED,
                    next_status,
                    run.version + 1,
                    (),
                    result_kind=command.result_kind,
                )

            if response.applied:
                self._persist_answer_context(unit_of_work, command, now_ms=now_ms)
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
                response = CompleteAnswerOnlyRunResult(
                    applied=True,
                    result_code=response.result_code,
                    current_status=response.current_status,
                    current_version=response.current_version,
                    next_allowed_commands=response.next_allowed_commands,
                    conflict_detail=response.conflict_detail,
                    assistant_message_id=assistant_message_id,
                    result_kind=response.result_kind,
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

    def _persist_answer_context(
        self,
        unit_of_work: UnitOfWork,
        command: CompleteAnswerOnlyRunCommand,
        *,
        now_ms: int,
    ) -> None:
        if not command.evidence_drafts:
            return
        if command.retrieval_artifact_id is None:
            raise ValueError("answer context requires retrieval_artifact_id")
        if command.resource_ref_drafts and self._tool_registry is None:
            raise RuntimeError("answer context resource persistence requires the tool registry")
        for resource_ref in command.resource_ref_drafts:
            if resource_ref.run_id != command.run_id:
                raise ValueError("answer context resource belongs to a different run")
            persist_registered_resource_ref(
                unit_of_work,
                resource_ref,
                catalog=cast(SignedToolRegistry, self._tool_registry),
            )
        refs_by_handle = {
            f"{record.resource_type}:{record.resource_id}": record
            for record in unit_of_work.resource_refs.list_for_run_bounded(
                command.run_id, limit=1000
            )
        }
        for draft in command.evidence_drafts:
            resource = refs_by_handle.get(draft["resource_handle"])
            if resource is None:
                raise LookupError(
                    f"answer evidence resource is unavailable: {draft['resource_handle']}"
                )
            role = draft["reason_codes"][0] if draft["reason_codes"] else ""
            if role not in {"SUPPORTS", "CONTRADICTS", "CONTEXT"}:
                raise ValueError("answer evidence role is invalid")
            unit_of_work.evidence.insert_bounded(
                EvidenceRecord(
                    id=self._evidence_id_factory(),
                    run_id=command.run_id,
                    origin_type=EvidenceOriginType.GOOGLE_RESOURCE,
                    resource_ref_id=resource.id,
                    message_id=None,
                    kind=draft["kind"],
                    excerpt=draft["excerpt"],
                    locator_json=dumps(
                        {
                            "retrieval_artifact_id": command.retrieval_artifact_id,
                            "segment_id": draft["segment_id"],
                            "role": role,
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )

    def _handle_existing_receipt(
        self,
        unit_of_work: UnitOfWork,
        command: CompleteAnswerOnlyRunCommand,
        existing_receipt: CommandReceiptRecord,
    ) -> CompleteAnswerOnlyRunResult:
        if existing_receipt.request_hash != command.request_hash:
            run = unit_of_work.runs.get(command.run_id)
            if run is None:
                raise DuplicateCommandError(command.command_id)
            return CompleteAnswerOnlyRunResult(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND,
                current_status=run.status,
                current_version=run.version,
                next_allowed_commands=next_allowed_run_commands(run.status),
                conflict_detail="command_id already exists with a different request_hash",
            )

        if (
            existing_receipt.response_json is not None
            and existing_receipt.status is not CommandReceiptStatus.RECEIVED
        ):
            response = _response_from_json(existing_receipt.response_json)
            if response.applied and response.result_kind is None:
                raise RuntimeError("terminal receipt is missing its result classification")
            return response

        return self._recover_pending_receipt(unit_of_work, command)

    def _recover_pending_receipt(
        self,
        unit_of_work: UnitOfWork,
        command: CompleteAnswerOnlyRunCommand,
    ) -> CompleteAnswerOnlyRunResult:
        run = unit_of_work.runs.get(command.run_id)
        if run is None:
            raise LookupError(f"run not found during receipt recovery: {command.run_id}")

        if run.status is RunStatusV1.COMPLETED:
            expected_content = self._build_terminal_message(
                BuildTerminalMessageQueryV1(
                    schema_version=1,
                    run_id=command.run_id,
                    expected_run_version=command.expected_version,
                    source_kind="ANSWER_DRAFT",
                    result_kind=command.result_kind,
                    answer_text=command.assistant_message,
                    reason_codes=[],
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
                response = CompleteAnswerOnlyRunResult(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED,
                    current_status=run.status,
                    current_version=run.version,
                    next_allowed_commands=next_allowed_run_commands(run.status),
                    assistant_message_id=message.id,
                    result_kind=command.result_kind,
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

        response = CompleteAnswerOnlyRunResult(
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


def _response_json(response: CompleteAnswerOnlyRunResult) -> str:
    return dumps(
        {
            "applied": response.applied,
            "result_code": response.result_code.value,
            "current_status": response.current_status.value,
            "current_version": response.current_version,
            "next_allowed_commands": [item.value for item in response.next_allowed_commands],
            "conflict_detail": response.conflict_detail,
            "assistant_message_id": response.assistant_message_id,
            "result_kind": response.result_kind,
        },
        sort_keys=True,
    )


def _response_from_json(raw: str) -> CompleteAnswerOnlyRunResult:
    payload = loads(raw)
    return CompleteAnswerOnlyRunResult(
        applied=bool(payload["applied"]),
        result_code=ResultCode(str(payload["result_code"])),
        current_status=RunStatusV1(str(payload["current_status"])),
        current_version=int(payload["current_version"]),
        next_allowed_commands=tuple(
            RunCommand(str(value)) for value in payload["next_allowed_commands"]
        ),
        conflict_detail=cast(str | None, payload.get("conflict_detail")),
        assistant_message_id=cast(str | None, payload.get("assistant_message_id")),
        result_kind=cast(Literal["SUCCESS", "PARTIAL"] | None, payload.get("result_kind")),
    )


__all__ = [
    "CompleteAnswerOnlyRunCommand",
    "CompleteAnswerOnlyRunResult",
    "CompleteAnswerOnlyRunHandler",
]
