"""Command-receipt persistence port."""

from typing import Protocol

from google_work_agent.domain.command_receipt.model import AnswerOnlyResponse
from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.results import ResultCode


class CommandReceiptRepository(Protocol):
    def get_by_command_id(self, command_id: str) -> CommandReceiptRecord | None: ...
    def add_received(
        self,
        *,
        command_id: str,
        command_type: str,
        request_hash: str,
        aggregate_type: str,
        aggregate_id: str | None,
        created_at_ms: int,
    ) -> None: ...
    def finish(
        self, *, command_id: str, response: AnswerOnlyResponse, completed_at_ms: int
    ) -> None: ...
    def finish_json(
        self,
        *,
        command_id: str,
        applied: bool,
        result_code: ResultCode,
        result_version: int,
        response_json: str,
        completed_at_ms: int,
    ) -> None: ...
    def has_applied_request_cancel(self, run_id: str) -> bool: ...
