"""Generic run terminal and reauth transitions for the workflow boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from json import dumps, loads
from typing import cast

from google_work_agent.application.orchestration.contracts import (
    AnalysisResult,
    ApiAcquisitionResult,
    FinalizeIntent,
    FinalizeIntentV1,
    PlanningResult,
    ReviewResult,
    WorkflowPhase,
    validate_finalize_intent_v1,
)
from google_work_agent.application.write_persistence import revoke_active_approvals
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.conversation.model import Conversation as ConversationRecord
from google_work_agent.domain.recovery.transitions.require_recovery import (
    transition_require_recovery,
)
from google_work_agent.domain.results import CommandResult, ResultCode
from google_work_agent.domain.run.model import Run as RunRecord
from google_work_agent.domain.run.model import (
    RunCommand,
    RunStatusV1,
    RunTransitionRejected,
    next_allowed_run_commands,
)
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import (
    UnitOfWork,
)
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple


@dataclass(frozen=True, slots=True)
class FailRunCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_version: int
    reason_code: str


@dataclass(frozen=True, slots=True)
class RunTransitionResponse:
    applied: bool
    result_code: str
    run_id: str
    run_status: str
    run_version: int
    next_allowed_commands: tuple[str, ...]
    reason_code: str | None = None
    result_kind: str | None = None
    conflict_detail: str | None = None


class FailRunService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: FailRunCommand) -> RunTransitionResponse:
        return _apply_run_transition(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
            command_id=command.command_id,
            command_type="FailRun",
            request_hash=command.request_hash,
            run_id=command.run_id,
            expected_version=command.expected_version,
            reason_code=command.reason_code,
            target_status=RunStatusV1.RECOVERY_REQUIRED,
            event_type="RUN_RECOVERY_REQUIRED",
            actor_id="fail_run",
            persist_finished_at_ms=False,
        )


def derive_finalize_intent(
    *,
    state: Mapping[str, object],
) -> FinalizeIntentV1 | None:
    persisted_intent = state.get("finalize_intent")
    if persisted_intent is not None:
        return validate_finalize_intent_v1(persisted_intent)

    answer_draft = _mapping_or_none(state.get("answer_draft"))
    plan_review = _mapping_or_none(state.get("plan_review"))
    if (
        answer_draft is not None
        and answer_draft.get("status") == PlanningResult.ANSWER_ONLY.value
        and plan_review is not None
        and plan_review.get("status") == ReviewResult.PASS.value
    ):
        return validate_finalize_intent_v1(
            {
                "schema_version": 1,
                "intent": FinalizeIntent.COMPLETED.value,
                "reason_code": "ANSWER_ONLY_REVIEW_PASS",
            }
        )

    context_result = _mapping_or_none(state.get("context_result"))
    if context_result is not None and context_result.get("status") == "BLOCKED":
        return validate_finalize_intent_v1(
            {
                "schema_version": 1,
                "intent": FinalizeIntent.BLOCKED.value,
                "reason_code": "CONTEXT_BLOCKED",
            }
        )

    analysis_result = _mapping_or_none(state.get("analysis_result"))
    if (
        analysis_result is not None
        and analysis_result.get("status") == AnalysisResult.BLOCKED.value
    ):
        return validate_finalize_intent_v1(
            {
                "schema_version": 1,
                "intent": FinalizeIntent.BLOCKED.value,
                "reason_code": "WORK_ANALYSIS_BLOCKED",
            }
        )

    if plan_review is not None and plan_review.get("status") == ReviewResult.BLOCK.value:
        return validate_finalize_intent_v1(
            {
                "schema_version": 1,
                "intent": FinalizeIntent.BLOCKED.value,
                "reason_code": "PLAN_REVIEW_BLOCK",
            }
        )

    acquisition_result = _mapping_or_none(state.get("acquisition_result"))
    if (
        acquisition_result is not None
        and acquisition_result.get("status") == ApiAcquisitionResult.FAILED.value
    ):
        return validate_finalize_intent_v1(
            {
                "schema_version": 1,
                "intent": FinalizeIntent.FAILED.value,
                "reason_code": _acquisition_failure_reason(acquisition_result),
            }
        )

    return None


def build_finalize_state_update(
    *,
    intent: str,
    reason_code: str,
    result_kind: str | None = None,
) -> dict[str, object]:
    finalize_intent = validate_finalize_intent_v1(
        {
            "schema_version": 1,
            "intent": intent,
            "reason_code": reason_code,
            "result_kind": result_kind,
        }
    )
    return {
        "workflow_phase": WorkflowPhase.FINALIZE.value,
        "finalize_intent": finalize_intent,
    }


def _apply_run_transition(
    *,
    unit_of_work_factory: Callable[[], UnitOfWork],
    now_ms: Callable[[], int],
    command_id: str,
    command_type: str,
    request_hash: str,
    run_id: str,
    expected_version: int,
    reason_code: str,
    target_status: RunStatusV1,
    event_type: str,
    actor_id: str,
    persist_finished_at_ms: bool,
) -> RunTransitionResponse:
    with unit_of_work_factory() as unit_of_work:
        existing = unit_of_work.command_receipts.get_by_command_id(command_id)
        completed_at_ms = now_ms()
        if existing is not None:
            return _handle_existing_receipt(
                unit_of_work=unit_of_work,
                receipt=existing,
                request_hash=request_hash,
                run_id=run_id,
                target_status=target_status,
                reason_code=reason_code,
                completed_at_ms=completed_at_ms,
            )

        unit_of_work.command_receipts.reserve_or_replay(
            command_id=command_id,
            command_type=command_type,
            request_hash=request_hash,
            aggregate_type="Run",
            aggregate_id=run_id,
            created_at_ms=completed_at_ms,
        )
        run = _require_run(unit_of_work, run_id)
        conversation = _require_conversation(unit_of_work, run.conversation_id)
        result = _run_transition_result(
            unit_of_work=unit_of_work,
            run=run,
            expected_version=expected_version,
            target_status=target_status,
        )
        if result.applied:
            if target_status is RunStatusV1.RECOVERY_REQUIRED:
                _revoke_active_approvals_for_run(unit_of_work=unit_of_work, run_id=run_id)
            values: dict[str, object] = {
                "status": result.current_status.value,
                "version": result.current_version,
            }
            if persist_finished_at_ms:
                values["finished_at_ms"] = completed_at_ms
            if not unit_of_work.runs.update_if_version_and_status(
                run.id,
                run.version,
                frozenset({run.status}),
                values,
            ):
                result = CommandResult(
                    False,
                    ResultCode.VERSION_CONFLICT,
                    run.status,
                    run.version,
                    next_allowed_run_commands(run.status),
                    "validated Run CAS failed",
                )
        response = RunTransitionResponse(
            applied=bool(result.applied),
            result_code=result.result_code.value,
            run_id=run_id,
            run_status=result.current_status.value,
            run_version=result.current_version,
            next_allowed_commands=tuple(item.value for item in result.next_allowed_commands),
            reason_code=reason_code,
            result_kind=result.current_status.value if result.applied else None,
            conflict_detail=result.conflict_detail,
        )
        if result.applied:
            unit_of_work.traces.append(
                TraceEventRecord(
                    run_id=run_id,
                    action_id=None,
                    event_type=event_type,
                    status=result.current_status.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {
                            "command_id": command_id,
                            "command_type": command_type,
                            "reason_code": reason_code,
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=completed_at_ms,
                )
            )
            unit_of_work.audits.append(
                AuditEventRecord(
                    account_id=conversation.account_id,
                    run_id=run_id,
                    action_id=None,
                    actor_type="AGENT",
                    actor_id=actor_id,
                    actor_display=command_type,
                    event_type=event_type,
                    outcome=result.result_code.value,
                    metadata_json=dumps(
                        {
                            "command_id": command_id,
                            "reason_code": reason_code,
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=completed_at_ms,
                )
            )
        _finish_json_receipt(
            unit_of_work=unit_of_work,
            command_id=command_id,
            response=response,
            completed_at_ms=completed_at_ms,
        )
        unit_of_work.commit()
        return response


def _run_transition_result(
    *,
    unit_of_work: UnitOfWork,
    run: RunRecord,
    expected_version: int,
    target_status: RunStatusV1,
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
    try:
        if target_status is RunStatusV1.RECOVERY_REQUIRED:
            next_status = transition_require_recovery(run.status)
        else:
            raise ValueError(f"unsupported exact Run transition target: {target_status.value}")
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


def _handle_existing_receipt(
    *,
    unit_of_work: UnitOfWork,
    receipt: CommandReceiptRecord,
    request_hash: str,
    run_id: str,
    target_status: RunStatusV1,
    reason_code: str,
    completed_at_ms: int,
) -> RunTransitionResponse:
    if receipt.request_hash != request_hash:
        run = _require_run(unit_of_work, run_id)
        return RunTransitionResponse(
            applied=False,
            result_code=ResultCode.DUPLICATE_COMMAND.value,
            run_id=run.id,
            run_status=run.status.value,
            run_version=run.version,
            next_allowed_commands=tuple(
                item.value for item in next_allowed_run_commands(run.status)
            ),
            reason_code=reason_code,
            conflict_detail="command_id already exists with a different request_hash",
        )
    if receipt.response_json is not None and receipt.status is not CommandReceiptStatus.RECEIVED:
        return _deserialize_run_transition_response(receipt.response_json)

    run = _require_run(unit_of_work, run_id)
    if run.status is target_status:
        response = RunTransitionResponse(
            applied=True,
            result_code=ResultCode.TRANSITION_APPLIED.value,
            run_id=run.id,
            run_status=run.status.value,
            run_version=run.version,
            next_allowed_commands=tuple(
                item.value for item in next_allowed_run_commands(run.status)
            ),
            reason_code=reason_code,
            result_kind=run.status.value,
        )
        _finish_json_receipt(
            unit_of_work=unit_of_work,
            command_id=receipt.command_id,
            response=response,
            completed_at_ms=completed_at_ms,
        )
        unit_of_work.commit()
        return response

    response = RunTransitionResponse(
        applied=False,
        result_code=ResultCode.RECOVERY_REQUIRED.value,
        run_id=run.id,
        run_status=run.status.value,
        run_version=run.version,
        next_allowed_commands=tuple(item.value for item in next_allowed_run_commands(run.status)),
        reason_code=reason_code,
        conflict_detail="receipt exists in RECEIVED state; aggregate recovery is inconclusive",
    )
    _finish_json_receipt(
        unit_of_work=unit_of_work,
        command_id=receipt.command_id,
        response=response,
        completed_at_ms=completed_at_ms,
    )
    unit_of_work.commit()
    return response


def _finish_json_receipt(
    *,
    unit_of_work: UnitOfWork,
    command_id: str,
    response: RunTransitionResponse,
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


def _deserialize_run_transition_response(raw: str) -> RunTransitionResponse:
    payload = loads(raw)
    return RunTransitionResponse(
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


def _require_run(unit_of_work: UnitOfWork, run_id: str) -> RunRecord:
    run = unit_of_work.runs.get(run_id)
    if run is None:
        raise LookupError(f"run not found: {run_id}")
    return run


def _require_conversation(unit_of_work: UnitOfWork, conversation_id: str) -> ConversationRecord:
    conversation = unit_of_work.conversations.get(conversation_id)
    if conversation is None:
        raise LookupError(f"conversation not found: {conversation_id}")
    return conversation


def _revoke_active_approvals_for_run(*, unit_of_work: UnitOfWork, run_id: str) -> None:
    for plan in current_plan_tuple(unit_of_work.plans, run_id):
        for action in unit_of_work.actions.list_for_plan(plan.id):
            revoke_active_approvals(unit_of_work, action.id)


def _mapping_or_none(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast(dict[str, object], value)


def _acquisition_failure_reason(acquisition_result: dict[str, object]) -> str:
    source_summaries = acquisition_result.get("source_summaries")
    if isinstance(source_summaries, list):
        for item in source_summaries:
            if isinstance(item, dict):
                error_code = item.get("error_code")
                if isinstance(error_code, str) and error_code.strip():
                    return error_code.strip()
    return "API_ACQUISITION_FAILED"


__all__ = [
    "build_finalize_state_update",
    "FailRunCommand",
    "FailRunService",
    "RunTransitionResponse",
    "derive_finalize_intent",
]
