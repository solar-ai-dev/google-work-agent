"""Conversation creation use case with durable idempotency."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from google_work_agent.application.run_command_receipts import (
    finish_json_receipt as _finish_json_receipt,
)
from google_work_agent.application.run_command_receipts import (
    resolve_existing_receipt as _resolve_existing_receipt,
)
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationCommand,
    CreateConversationResult as CreateConversationResponse,
)
from google_work_agent.domain import ResultCode
from google_work_agent.ports import ConversationRecord, UnitOfWork


class CreateConversationService:
    """Create conversations with durable idempotency."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: CreateConversationCommand) -> CreateConversationResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return cast(
                    CreateConversationResponse,
                    _resolve_existing_receipt(
                        unit_of_work=unit_of_work,
                        receipt=existing,
                        request_hash=command.request_hash,
                        response_type=CreateConversationResponse,
                        now_ms=self._now_ms(),
                    ),
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="CreateConversation",
                request_hash=command.request_hash,
                aggregate_type="Conversation",
                aggregate_id=command.conversation_id,
                created_at_ms=now_ms,
            )
            unit_of_work.conversations.add(
                ConversationRecord(
                    id=command.conversation_id,
                    account_id=command.account_id,
                    title=command.title,
                    created_at_ms=now_ms,
                    updated_at_ms=now_ms,
                )
            )
            response = CreateConversationResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                conversation_id=command.conversation_id,
                account_id=command.account_id,
                title=command.title,
                updated_at_ms=now_ms,
            )
            _finish_json_receipt(
                unit_of_work=unit_of_work,
                command_id=command.command_id,
                response=response,
                result_version=0,
                completed_at_ms=now_ms,
            )
            unit_of_work.commit()
            return response
