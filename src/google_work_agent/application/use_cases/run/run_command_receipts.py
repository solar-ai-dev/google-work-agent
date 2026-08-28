"""Run-owner-local command receipt serialization."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from json import dumps
from typing import cast

from google_work_agent.application.use_cases.action.write_persistence import (
    emit_command_rejected_hash_mismatch,
)
from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.results import ResultCode
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ActionMutationReceiptResponse:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None


type ReceiptResponse = object


def resolve_json_receipt(
    *,
    receipt: CommandReceiptRecord,
    request_hash: str,
    response_type: type[object],
) -> ReceiptResponse:
    from json import loads

    from google_work_agent.application.use_cases.conversation.create_conversation import (
        CreateConversationResult,
    )
    from google_work_agent.application.use_cases.run.resume_after_reauth import (
        ResumeAfterReauthResult,
    )

    request_hash_value = receipt.request_hash
    if request_hash_value != request_hash:
        aggregate_id = receipt.aggregate_id or ""
        result_version = receipt.result_version or 0
        if response_type is CreateConversationResult:
            return CreateConversationResult(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                conversation_id=aggregate_id,
                account_id="",
                title="",
                updated_at_ms=0,
                conflict_detail="command_id already exists with a different request_hash",
            )
        if response_type is ResumeAfterReauthResult:
            return ResumeAfterReauthResult(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                run_id=aggregate_id,
                run_status="UNKNOWN",
                run_version=result_version,
                should_enqueue=False,
                request_replayed=True,
                conflict_detail="command_id already exists with a different request_hash",
            )
        return ActionMutationReceiptResponse(
            applied=False,
            result_code=ResultCode.DUPLICATE_COMMAND.value,
            action_id=aggregate_id,
            action_status="UNKNOWN",
            action_version=result_version,
            next_allowed_commands=(),
            conflict_detail="command_id already exists with a different request_hash",
        )

    response_json = receipt.response_json
    status = receipt.status
    if response_json is None or status is CommandReceiptStatus.RECEIVED:
        raise RuntimeError("RECEIVED receipt recovery requires aggregate-specific handling")
    payload = loads(response_json)
    if "next_allowed_commands" in payload:
        payload["next_allowed_commands"] = tuple(payload["next_allowed_commands"])
    return cast(ReceiptResponse, response_type(**payload))


def resolve_existing_receipt(
    *,
    unit_of_work: UnitOfWork,
    receipt: CommandReceiptRecord,
    request_hash: str,
    response_type: type[object],
    run_id: str | None = None,
    action_id: str | None = None,
    now_ms: int,
) -> ReceiptResponse:
    """Thin wrapper shared by every CreateConversation/ResumeRun/
    ActionMutation caller of the pure resolve_json_receipt above.

    Keeps resolve_json_receipt itself free of side effects; records
    COMMAND_REJECTED_HASH_MISMATCH via the one shared observability boundary
    (write_persistence.emit_command_rejected_hash_mismatch) only for a
    genuine different-hash conflict, never for a same-hash idempotent
    replay.
    """
    if receipt.request_hash != request_hash:
        emit_command_rejected_hash_mismatch(
            unit_of_work=unit_of_work,
            receipt=receipt,
            run_id=run_id,
            action_id=action_id,
            now_ms=now_ms,
        )
    return resolve_json_receipt(
        receipt=receipt,
        request_hash=request_hash,
        response_type=response_type,
    )


def finish_json_receipt(
    unit_of_work: UnitOfWork,
    command_id: str,
    response: ReceiptResponse,
    result_version: int,
    completed_at_ms: int,
) -> None:
    unit_of_work.command_receipts.store_result(
        command_id=command_id,
        applied=bool(response.applied),
        result_code=ResultCode(str(response.result_code)),
        result_version=result_version,
        response_json=dumps(asdict(response), sort_keys=True),
        completed_at_ms=completed_at_ms,
    )
