"""Canonical persisted BlockRun application authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads
from typing import cast
from uuid import uuid4

from google_work_agent.application.use_cases.action.persistence_cas import (
    update_action_record,
    update_plan_record,
)
from google_work_agent.application.use_cases.action.write_persistence import revoke_active_approvals
from google_work_agent.application.use_cases.plan.persistence_projection import current_plan_tuple
from google_work_agent.application.use_cases.run.build_terminal_message import (
    BuildTerminalMessageHandler,
    BuildTerminalMessageQueryV1,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.message.model import Message as MessageRecord
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import CommandResult, ResultCode
from google_work_agent.domain.run.model import Run as RunRecord
from google_work_agent.domain.run.model import (
    RunCommand,
    RunStatusV1,
    RunTransitionRejected,
    next_allowed_run_commands,
)
from google_work_agent.domain.run.transitions.block_run import transition_block_run
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.persistence.approval_repository import active_approval_tuple
from google_work_agent.ports.persistence.execution_attempt_repository import active_attempt_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class BlockRunCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_version: int
    reason_code: str
    policy_origin: bool = False


@dataclass(frozen=True, slots=True)
class BlockRunResult:
    applied: bool
    result_code: str
    run_id: str
    run_status: str
    run_version: int
    next_allowed_commands: tuple[str, ...]
    reason_code: str | None = None
    result_kind: str | None = None
    conflict_detail: str | None = None


class BlockRunHandler:
    """Validate child facts and atomically settle the blocked aggregate."""

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

    def __call__(self, command: BlockRunCommand) -> BlockRunResult:
        terminal_message = self._build_terminal_message(
            BuildTerminalMessageQueryV1(
                schema_version=1,
                run_id=command.run_id,
                expected_run_version=command.expected_version,
                source_kind="POLICY_BLOCK" if command.policy_origin else "INVALID_REQUEST",
                result_kind="BLOCKED",
                answer_text=None,
                reason_codes=[command.reason_code],
            )
        )
        with self._unit_of_work_factory() as unit_of_work:
            completed_at_ms = self._now_ms()
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._replay(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    command=command,
                    completed_at_ms=completed_at_ms,
                )

            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="BlockRun",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=completed_at_ms,
            )
            run = self._require_run(unit_of_work, command.run_id)
            conversation = unit_of_work.conversations.get(run.conversation_id)
            if conversation is None:
                raise LookupError(f"conversation not found: {run.conversation_id}")
            result = self._transition(unit_of_work, run, command.expected_version)
            if result.applied:
                self._settle_children(
                    unit_of_work=unit_of_work,
                    run_id=command.run_id,
                    updated_at_ms=completed_at_ms,
                )
                if not unit_of_work.runs.update_if_version_and_status(
                    run.id,
                    run.version,
                    frozenset({run.status}),
                    {
                        "status": result.current_status.value,
                        "version": result.current_version,
                        "finished_at_ms": completed_at_ms,
                        "terminal_result_kind": "BLOCKED",
                    },
                ):
                    result = CommandResult(
                        False,
                        ResultCode.VERSION_CONFLICT,
                        run.status,
                        run.version,
                        next_allowed_run_commands(run.status),
                        "validated Run CAS failed",
                    )
            response = self._response(command, result)
            if result.applied:
                message_id = self._message_id_factory()
                unit_of_work.messages.append_terminal_assistant_message(
                    MessageRecord(
                        id=message_id,
                        conversation_id=conversation.id,
                        run_id=command.run_id,
                        role="ASSISTANT",
                        content=terminal_message.content,
                        created_at_ms=completed_at_ms,
                    )
                )
                unit_of_work.traces.append(
                    TraceEventRecord(
                        run_id=command.run_id,
                        action_id=None,
                        event_type="RUN_BLOCKED",
                        status=result.current_status.value,
                        duration_ms=None,
                        payload_json=dumps(
                            {
                                "command_id": command.command_id,
                                "command_type": "BlockRun",
                                "reason_code": command.reason_code,
                                "message_id": message_id,
                            },
                            sort_keys=True,
                        ),
                        created_at_ms=completed_at_ms,
                    )
                )
                unit_of_work.audits.append(
                    AuditEventRecord(
                        account_id=conversation.account_id,
                        run_id=command.run_id,
                        action_id=None,
                        actor_type="AGENT",
                        actor_id="block_run",
                        actor_display="BlockRun",
                        event_type="RUN_BLOCKED",
                        outcome=result.result_code.value,
                        metadata_json=dumps(
                            {
                                "command_id": command.command_id,
                                "reason_code": command.reason_code,
                                "message_id": message_id,
                            },
                            sort_keys=True,
                        ),
                        created_at_ms=completed_at_ms,
                    )
                )
                if command.policy_origin:
                    unit_of_work.audits.append(
                        AuditEventRecord(
                            account_id=conversation.account_id,
                            run_id=command.run_id,
                            action_id=None,
                            actor_type="SYSTEM",
                            actor_id="block_run",
                            actor_display="BlockRun",
                            event_type="POLICY_BLOCKED",
                            outcome=result.result_code.value,
                            metadata_json=dumps(
                                {
                                    "command_id": command.command_id,
                                    "reason_code": command.reason_code,
                                },
                                sort_keys=True,
                            ),
                            created_at_ms=completed_at_ms,
                        )
                    )
            self._finish_receipt(unit_of_work, command.command_id, response, completed_at_ms)
            unit_of_work.commit()
            return response

    @staticmethod
    def _transition(
        unit_of_work: UnitOfWork,
        run: RunRecord,
        expected_version: int,
    ) -> CommandResult[RunStatusV1, RunCommand]:
        if run.version != expected_version:
            return CommandResult(
                False,
                ResultCode.VERSION_CONFLICT,
                run.status,
                run.version,
                next_allowed_run_commands(run.status),
                "expected_version does not match current_version",
            )
        plans = tuple(
            plan
            for plan in current_plan_tuple(unit_of_work.plans, run.id)
            if plan.status is not PlanStatusV1.SUPERSEDED
        )
        current_plan = plans[0] if len(plans) == 1 else None
        actions = (
            () if current_plan is None else unit_of_work.actions.list_for_plan(current_plan.id)
        )
        attempts = tuple(
            attempt
            for action in actions
            for approval in active_approval_tuple(unit_of_work.approvals, action.id)
            for attempt in active_attempt_tuple(unit_of_work.execution_attempts, approval.id)
        )
        try:
            next_status = transition_block_run(
                run.status,
                plan_status=None if current_plan is None else current_plan.status,
                plan_is_current=len(plans) <= 1,
                review_disposition=(
                    None if current_plan is None else current_plan.review_disposition
                ),
                action_statuses=tuple(ActionStatusV1(action.status) for action in actions),
                attempt_statuses=tuple(attempt.status for attempt in attempts),
            )
        except RunTransitionRejected as error:
            return CommandResult(
                False,
                ResultCode.STATE_CONFLICT,
                run.status,
                run.version,
                next_allowed_run_commands(run.status),
                str(error),
            )
        return CommandResult(
            True,
            ResultCode.TRANSITION_APPLIED,
            next_status,
            run.version + 1,
            next_allowed_run_commands(next_status),
        )

    @staticmethod
    def _settle_children(*, unit_of_work: UnitOfWork, run_id: str, updated_at_ms: int) -> None:
        pending = {
            ActionStatusV1.PROPOSED.value,
            ActionStatusV1.MODIFIED.value,
            ActionStatusV1.APPROVED.value,
            ActionStatusV1.EXPIRED.value,
        }
        for plan in current_plan_tuple(unit_of_work.plans, run_id):
            if plan.status in {
                PlanStatusV1.SUPERSEDED,
                PlanStatusV1.COMPLETED,
                PlanStatusV1.CANCELLED,
            }:
                continue
            actions = unit_of_work.actions.list_for_plan(plan.id)
            for action in actions:
                revoke_active_approvals(unit_of_work, action.id)
            for action in actions:
                if action.status not in pending:
                    continue
                if (
                    update_action_record(
                        unit_of_work,
                        action.id,
                        expected_version=action.version,
                        expected_status=ActionStatusV1(action.status),
                        next_status=ActionStatusV1.BLOCKED,
                        updated_at_ms=updated_at_ms,
                    )
                    is None
                ):
                    raise RuntimeError(f"BlockRun could not terminalize pending action {action.id}")
            if (
                update_plan_record(
                    unit_of_work,
                    plan.id,
                    expected_status=plan.status,
                    next_status=PlanStatusV1.CANCELLED,
                )
                is None
            ):
                raise RuntimeError(f"BlockRun could not cancel Plan {plan.id}")

    def _replay(
        self,
        *,
        unit_of_work: UnitOfWork,
        receipt: CommandReceiptRecord,
        command: BlockRunCommand,
        completed_at_ms: int,
    ) -> BlockRunResult:
        run = self._require_run(unit_of_work, command.run_id)
        if receipt.request_hash != command.request_hash:
            return BlockRunResult(
                False,
                ResultCode.DUPLICATE_COMMAND.value,
                run.id,
                run.status.value,
                run.version,
                tuple(item.value for item in next_allowed_run_commands(run.status)),
                command.reason_code,
                conflict_detail="command_id already exists with a different request_hash",
            )
        if (
            receipt.response_json is not None
            and receipt.status is not CommandReceiptStatus.RECEIVED
        ):
            payload = loads(receipt.response_json)
            return BlockRunResult(
                applied=bool(payload["applied"]),
                result_code=str(payload["result_code"]),
                run_id=str(payload["run_id"]),
                run_status=str(payload["run_status"]),
                run_version=int(payload["run_version"]),
                next_allowed_commands=tuple(str(item) for item in payload["next_allowed_commands"]),
                reason_code=cast(str | None, payload.get("reason_code")),
                result_kind=cast(str | None, payload.get("result_kind")),
                conflict_detail=cast(str | None, payload.get("conflict_detail")),
            )
        response = BlockRunResult(
            applied=run.status is RunStatusV1.BLOCKED,
            result_code=(
                ResultCode.TRANSITION_APPLIED.value
                if run.status is RunStatusV1.BLOCKED
                else ResultCode.RECOVERY_REQUIRED.value
            ),
            run_id=run.id,
            run_status=run.status.value,
            run_version=run.version,
            next_allowed_commands=tuple(
                item.value for item in next_allowed_run_commands(run.status)
            ),
            reason_code=command.reason_code,
            result_kind=run.status.value if run.status is RunStatusV1.BLOCKED else None,
            conflict_detail=(
                None
                if run.status is RunStatusV1.BLOCKED
                else "receipt exists in RECEIVED state; aggregate recovery is inconclusive"
            ),
        )
        self._finish_receipt(unit_of_work, receipt.command_id, response, completed_at_ms)
        unit_of_work.commit()
        return response

    @staticmethod
    def _response(
        command: BlockRunCommand,
        result: CommandResult[RunStatusV1, RunCommand],
    ) -> BlockRunResult:
        return BlockRunResult(
            applied=bool(result.applied),
            result_code=result.result_code.value,
            run_id=command.run_id,
            run_status=result.current_status.value,
            run_version=result.current_version,
            next_allowed_commands=tuple(item.value for item in result.next_allowed_commands),
            reason_code=command.reason_code,
            result_kind=result.current_status.value if result.applied else None,
            conflict_detail=result.conflict_detail,
        )

    @staticmethod
    def _finish_receipt(
        unit_of_work: UnitOfWork,
        command_id: str,
        response: BlockRunResult,
        completed_at_ms: int,
    ) -> None:
        unit_of_work.command_receipts.store_result(
            command_id=command_id,
            applied=response.applied,
            result_code=ResultCode(response.result_code),
            result_version=response.run_version,
            response_json=dumps(asdict(response), sort_keys=True),
            completed_at_ms=completed_at_ms,
        )

    @staticmethod
    def _require_run(unit_of_work: UnitOfWork, run_id: str) -> RunRecord:
        run = unit_of_work.runs.get(run_id)
        if run is None:
            raise LookupError(f"run not found: {run_id}")
        return run


__all__ = ["BlockRunCommand", "BlockRunHandler", "BlockRunResult"]
