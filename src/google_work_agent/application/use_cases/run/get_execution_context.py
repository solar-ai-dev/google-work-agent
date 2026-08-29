"""Get the persisted execution context for one run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.domain.message.model import Message as MessageRecord
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef


@dataclass(frozen=True, slots=True)
class GetExecutionContextQuery:
    run_id: str


@dataclass(frozen=True, slots=True)
class GetExecutionContextResult:
    run_id: str
    conversation_id: str
    workflow_key: str
    entry_mode: str
    requested_mode: str
    status: str
    version: int
    request_text: str
    selected_resource_ids: tuple[str, ...]
    selected_resources: tuple[SelectedResourceRef, ...] = ()


class GetExecutionContextHandler:
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def __call__(self, query: GetExecutionContextQuery) -> GetExecutionContextResult | None:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(query.run_id)
            if run is None:
                return None
            message = _first_user_message(unit_of_work, run.conversation_id, query.run_id)
            resources = unit_of_work.resource_refs.list_for_run_bounded(query.run_id, limit=200)
        selected_resource_ids = tuple(record.resource_id for record in resources)
        selected_resources = tuple(_selected_resource_ref(record) for record in resources)
        return GetExecutionContextResult(
            run_id=run.id,
            conversation_id=run.conversation_id,
            workflow_key=run.langgraph_thread_id,
            entry_mode=run.entry_mode,
            requested_mode=run.requested_mode,
            status=run.status.value,
            version=run.version,
            request_text="" if message is None else message.content,
            selected_resource_ids=selected_resource_ids,
            selected_resources=selected_resources,
        )


def _selected_resource_ref(value: object) -> SelectedResourceRef:
    durable_type = value.resource_type  # type: ignore[attr-defined]
    source, projected_type = {
        "gmail_thread": ("GMAIL", "THREAD"),
        "gmail_message": ("GMAIL", "MESSAGE"),
        "gmail_attachment": ("GMAIL", "ATTACHMENT"),
        "gmail_draft": ("GMAIL", "DRAFT"),
        "task_list": ("TASKS", "TASK_LIST"),
        "task": ("TASKS", "TASK"),
        "calendar": ("CALENDAR", "CALENDAR"),
        "calendar_event": ("CALENDAR", "EVENT"),
        "calendar_freebusy": ("CALENDAR", "FREEBUSY"),
    }[durable_type]
    return SelectedResourceRef(
        source=source,
        resource_type=projected_type,
        resource_id=value.resource_id,  # type: ignore[attr-defined]
        parent_resource_id=value.parent_resource_id,  # type: ignore[attr-defined]
    )


def _first_user_message(
    unit_of_work: UnitOfWork, conversation_id: str, run_id: str
) -> MessageRecord | None:
    cursor: str | None = None
    first = None
    while True:
        messages, cursor = unit_of_work.messages.list_by_conversation_keyset(
            conversation_id=conversation_id, cursor=cursor, page_size=200
        )
        for message in messages:
            if message.run_id == run_id and message.role == "USER":
                first = message
        if cursor is None:
            return first
