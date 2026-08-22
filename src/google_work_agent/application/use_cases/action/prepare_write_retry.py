"""Canonical Application owner for FAILED write retry preparation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from google_work_agent.application.write_actions import PrepareWriteRetryCommand as _LegacyPrepareWriteRetryCommand


class _PrepareRetryService(Protocol):
    def __call__(self, command: _LegacyPrepareWriteRetryCommand) -> object: ...


@dataclass(frozen=True, slots=True)
class PrepareWriteRetryCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class PrepareWriteRetryResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None


class PrepareWriteRetryHandler:
    def __init__(self, *, prepare_retry_service: _PrepareRetryService) -> None:
        self._prepare_retry_service = prepare_retry_service

    def __call__(self, command: PrepareWriteRetryCommand) -> PrepareWriteRetryResult:
        raw = self._prepare_retry_service(
            _LegacyPrepareWriteRetryCommand(
                command_id=command.command_id,
                request_hash=command.request_hash,
                action_id=command.action_id,
                expected_action_version=command.expected_version,
            )
        )
        return PrepareWriteRetryResult(
            applied=bool(getattr(raw, "applied")),
            result_code=str(getattr(raw, "result_code")),
            action_id=str(getattr(raw, "action_id")),
            action_status=str(getattr(raw, "action_status")),
            action_version=int(getattr(raw, "action_version")),
            next_allowed_commands=tuple(getattr(raw, "next_allowed_commands")),
            conflict_detail=getattr(raw, "conflict_detail"),
        )
