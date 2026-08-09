"""Generic run terminal and reauth transitions for the workflow boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from json import dumps, loads
from typing import cast

from google_work_agent.application.workflows import (
    AnalysisResult,
    ApiAcquisitionResult,
    FinalizeIntent,
    FinalizeIntentV1,
    PlanningResult,
    ReviewResult,
    WorkflowPhase,
    validate_finalize_intent_v1,
)
from google_work_agent.domain import ResultCode, RunStatus, next_allowed_run_commands
from google_work_agent.ports import (
    AuditEventRecord,
    CommandReceiptRecord,
    CommandReceiptStatus,
    ConversationRecord,
    RunRecord,
    TraceEventRecord,
    UnitOfWork,
)


@dataclass(frozen=True, slots=True)
class BlockRunCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_version: int
    reason_code: str


@dataclass(frozen=True, slots=True)
class FailRunCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_version: int
    reason_code: str


@dataclass(frozen=True, slots=True)
class CompleteWriteRunCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class RequireReauthCommand:
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


class BlockRunService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: BlockRunCommand) -> RunTransitionResponse:
        return _apply_run_transition(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
            command_id=command.command_id,
            command_type="BlockRun",
            request_hash=command.request_hash,
            run_id=command.run_id,
            expected_version=command.expected_version,
            reason_code=command.reason_code,
            target_status=RunStatus.BLOCKED,
            repository_call="block_run",
            event_type="RUN_BLOCKED",
            actor_id="block_run",
            persist_finished_at_ms=True,
        )


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
            target_status=RunStatus.FAILED,
            repository_call="fail_run",
            event_type="RUN_FAILED",
            actor_id="fail_run",
            persist_finished_at_ms=True,
        )


class RequireReauthService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: RequireReauthCommand) -> RunTransitionResponse:
        return _apply_run_transition(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
            command_id=command.command_id,
            command_type="RequireReauth",
            request_hash=command.request_hash,
            run_id=command.run_id,
            expected_version=command.expected_version,
            reason_code=command.reason_code,
            target_status=RunStatus.REAUTH_REQUIRED,
            repository_call="require_reauth",
            event_type="RUN_REAUTH_REQUIRED",
            actor_id="require_reauth",
            persist_finished_at_ms=False,
        )


class CompleteWriteRunService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: CompleteWriteRunCommand) -> RunTransitionResponse:
        return _apply_run_transition(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
            command_id=command.command_id,
            command_type="CompleteWriteRun",
            request_hash=command.request_hash,
            run_id=command.run_id,
            expected_version=command.expected_version,
            reason_code="WRITE_VERIFIED",
            target_status=RunStatus.COMPLETED,
            repository_call="complete_write_run",
            event_type="RUN_COMPLETED",
            actor_id="complete_write_run",
            persist_finished_at_ms=True,
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
    target_status: RunStatus,
    repository_call: str,
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

        unit_of_work.command_receipts.add_received(
            command_id=command_id,
            command_type=command_type,
            request_hash=request_hash,
            aggregate_type="Run",
            aggregate_id=run_id,
            created_at_ms=completed_at_ms,
        )
        run = _require_run(unit_of_work, run_id)
        conversation = _require_conversation(unit_of_work, run.conversation_id)
        repository_method = getattr(unit_of_work.runs, repository_call)
        kwargs = {
            "expected_version": expected_version,
            "finished_at_ms": completed_at_ms if persist_finished_at_ms else None,
        }
        result = repository_method(run_id, **kwargs)
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
            unit_of_work.traces.add(
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
            unit_of_work.audits.add(
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


def _handle_existing_receipt(
    *,
    unit_of_work: UnitOfWork,
    receipt: CommandReceiptRecord,
    request_hash: str,
    run_id: str,
    target_status: RunStatus,
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
    unit_of_work.command_receipts.finish_json(
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
    run = unit_of_work.runs.get_by_id(run_id)
    if run is None:
        raise LookupError(f"run not found: {run_id}")
    return run


def _require_conversation(unit_of_work: UnitOfWork, conversation_id: str) -> ConversationRecord:
    conversation = unit_of_work.conversations.get_by_id(conversation_id)
    if conversation is None:
        raise LookupError(f"conversation not found: {conversation_id}")
    return conversation


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
    "BlockRunCommand",
    "BlockRunService",
    "build_finalize_state_update",
    "FailRunCommand",
    "FailRunService",
    "RequireReauthCommand",
    "RequireReauthService",
    "RunTransitionResponse",
    "derive_finalize_intent",
]
