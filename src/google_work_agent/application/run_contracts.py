"""Application contracts for conversation and run lifecycle commands."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.ports import SelectedResourceRef


@dataclass(frozen=True, slots=True)
class StartRunCommand:
    command_id: str
    request_hash: str
    conversation_id: str
    user_message_id: str
    run_id: str
    workflow_key: str
    request_text: str
    entry_mode: str
    selected_resource_ids: tuple[str, ...]
    requested_mode: str
    api_contract_version: str
    selected_resources: tuple[SelectedResourceRef, ...] = ()


@dataclass(frozen=True, slots=True)
class StartRunResponse:
    applied: bool
    result_code: str
    run_id: str
    conversation_id: str
    run_status: str
    run_version: int
    user_message_id: str
    workflow_key: str
    enqueued: bool
    request_replayed: bool
    conflict_detail: str | None = None
