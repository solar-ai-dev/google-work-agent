"""Canonical persisted CompleteReadOnlyRun application boundary."""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads
from typing import Literal
from uuid import uuid4

from google_work_agent.application.use_cases.action.persistence_cas import update_plan_record
from google_work_agent.application.use_cases.plan.persistence_projection import (
    current_plan_tuple,
    load_plan_record,
)
from google_work_agent.application.use_cases.run.build_terminal_message import (
    BuildTerminalMessageHandler,
    BuildTerminalMessageQueryV1,
    TerminalAssistantMessageInputV1,
    validate_terminal_assistant_message_input,
)
from google_work_agent.application.use_cases.run.project_terminal_message_context import (
    project_terminal_message_context,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.audit_event.model import AuditEvent
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.message.model import Message
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.transitions.complete_read_only_run import (
    transition_complete_read_only_run,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class CompleteReadOnlyRunCommand:
    command_id: str
    request_hash: str
    run_id: str
    plan_id: str
    expected_version: int
    terminal_message: TerminalAssistantMessageInputV1 | None = None


@dataclass(frozen=True, slots=True)
class CompleteReadOnlyRunResult:
    applied: bool
    result_code: str
    run_id: str
    run_status: str
    run_version: int
    plan_id: str
    plan_status: str
    result_kind: str | None = None
    conflict_detail: str | None = None


class CompleteReadOnlyRunHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        message_id_factory: Callable[[], str] | None = None,
        build_terminal_message: BuildTerminalMessageHandler | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._message_id_factory = message_id_factory or (lambda: str(uuid4()))
        self._build_terminal_message = build_terminal_message or BuildTerminalMessageHandler()

    def __call__(self, command: CompleteReadOnlyRunCommand) -> CompleteReadOnlyRunResult:
        with self._unit_of_work_factory() as unit_of_work:
            result = self.apply_in_unit_of_work(
                unit_of_work,
                command,
                self._now_ms(),
                message_id_factory=self._message_id_factory,
                build_terminal_message=self._build_terminal_message,
            )
            unit_of_work.commit()
            return result

    @staticmethod
    def apply_in_unit_of_work(
        unit_of_work: UnitOfWork,
        command: CompleteReadOnlyRunCommand,
        now_ms: int,
        *,
        message_id_factory: Callable[[], str] | None = None,
        build_terminal_message: BuildTerminalMessageHandler | None = None,
    ) -> CompleteReadOnlyRunResult:
        receipt = unit_of_work.command_receipts.get_by_command_id(command.command_id)
        if receipt is not None:
            if receipt.request_hash != command.request_hash:
                return _current_result(
                    unit_of_work,
                    command,
                    ResultCode.DUPLICATE_COMMAND,
                    "command_id exists with a different request_hash",
                )
            if (
                receipt.response_json is not None
                and receipt.status is not CommandReceiptStatus.RECEIVED
            ):
                return CompleteReadOnlyRunResult(**loads(receipt.response_json))
            raise RuntimeError("RECEIVED CompleteReadOnlyRun receipt requires reconciliation")

        unit_of_work.command_receipts.reserve_or_replay(
            command_id=command.command_id,
            command_type="CompleteReadOnlyRun",
            request_hash=command.request_hash,
            aggregate_type="Run",
            aggregate_id=command.run_id,
            created_at_ms=now_ms,
        )
        run = unit_of_work.runs.get(command.run_id)
        plan = load_plan_record(unit_of_work.plans, command.plan_id)
        if run is None or plan is None or plan.run_id != run.id:
            raise LookupError("CompleteReadOnlyRun aggregate not found")
        current_plans = tuple(
            candidate
            for candidate in current_plan_tuple(unit_of_work.plans, run.id)
            if candidate.status is not PlanStatusV1.SUPERSEDED
        )
        statuses = tuple(
            ActionStatusV1(action.status) for action in unit_of_work.actions.list_for_plan(plan.id)
        )
        if run.version != command.expected_version:
            result = _current_result(
                unit_of_work,
                command,
                ResultCode.VERSION_CONFLICT,
                "expected_version does not match current_version",
            )
        else:
            next_run, next_plan = transition_complete_read_only_run(
                run.status,
                plan_status=plan.status,
                action_statuses=statuses,
            )
            if len(current_plans) != 1 or current_plans[0].id != plan.id:
                raise RuntimeError("CompleteReadOnlyRun requires current Plan authority")
            if (
                update_plan_record(
                    unit_of_work, plan.id, expected_status=plan.status, next_status=next_plan
                )
                is None
            ):
                raise RuntimeError("validated CompleteReadOnlyRun Plan CAS failed")
            result_kind: Literal["SUCCESS", "PARTIAL"] = (
                "PARTIAL" if ActionStatusV1.FAILED in statuses else "SUCCESS"
            )
            if not unit_of_work.runs.update_if_version_and_status(
                run.id,
                run.version,
                frozenset({run.status}),
                {
                    "status": next_run.value,
                    "version": run.version + 1,
                    "finished_at_ms": now_ms,
                    "terminal_result_kind": result_kind,
                },
            ):
                raise RuntimeError("validated CompleteReadOnlyRun Run CAS failed")
            result = CompleteReadOnlyRunResult(
                True,
                ResultCode.TRANSITION_APPLIED.value,
                run.id,
                next_run.value,
                run.version + 1,
                plan.id,
                next_plan.value,
                result_kind,
            )
            unit_of_work.audits.append(
                AuditEvent(
                    account_id=None,
                    run_id=run.id,
                    action_id=None,
                    actor_type="AGENT",
                    actor_id="complete_read_only_run",
                    actor_display="CompleteReadOnlyRun",
                    event_type="RUN_COMPLETED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata_json=dumps(
                        {
                            "command_id": command.command_id,
                            "completion_mode": "READ_ONLY",
                            "result_kind": result_kind,
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            terminal_message = command.terminal_message
            if terminal_message is None:
                request_text, action_outcomes = project_terminal_message_context(
                    unit_of_work, run.id
                )
                terminal_message = (build_terminal_message or BuildTerminalMessageHandler())(
                    BuildTerminalMessageQueryV1(
                        schema_version=1,
                        run_id=run.id,
                        expected_run_version=command.expected_version,
                        source_kind="READ_RESULT_SUMMARY",
                        result_kind=result_kind,
                        answer_text=None,
                        reason_codes=(["READ_ACTION_FAILED"] if result_kind == "PARTIAL" else []),
                        request_text=request_text,
                        action_outcomes=action_outcomes,
                    )
                )
            validate_terminal_assistant_message_input(terminal_message)
            if terminal_message.result_kind != result_kind:
                raise RuntimeError(
                    "terminal message result kind does not match durable read result"
                )
            unit_of_work.messages.append_terminal_assistant_message(
                Message(
                    id=(message_id_factory or (lambda: str(uuid4())))(),
                    conversation_id=run.conversation_id,
                    run_id=run.id,
                    role="ASSISTANT",
                    content=terminal_message.content,
                    created_at_ms=now_ms,
                )
            )
        unit_of_work.command_receipts.store_result(
            command_id=command.command_id,
            applied=result.applied,
            result_code=ResultCode(result.result_code),
            result_version=result.run_version,
            response_json=dumps(asdict(result), sort_keys=True),
            completed_at_ms=now_ms,
        )
        return result


def _current_result(
    unit_of_work: UnitOfWork,
    command: CompleteReadOnlyRunCommand,
    code: ResultCode,
    detail: str,
) -> CompleteReadOnlyRunResult:
    run = unit_of_work.runs.get(command.run_id)
    plan = load_plan_record(unit_of_work.plans, command.plan_id)
    if run is None or plan is None:
        raise LookupError("CompleteReadOnlyRun aggregate not found")
    return CompleteReadOnlyRunResult(
        False,
        code.value,
        run.id,
        run.status.value,
        run.version,
        plan.id,
        plan.status.value,
        conflict_detail=detail,
    )


__all__ = [
    "CompleteReadOnlyRunCommand",
    "CompleteReadOnlyRunHandler",
    "CompleteReadOnlyRunResult",
]
