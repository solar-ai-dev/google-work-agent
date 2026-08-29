"""Dispatch one validated Google Workspace MCP tool operation."""

from collections.abc import Callable
from typing import Protocol

from google_work_agent.adapters.connectors.google.calendar.calendars.list_calendars import (
    ListCalendarsOperation,
)
from google_work_agent.adapters.connectors.google.calendar.events.create_event import (
    CreateEventOperation,
)
from google_work_agent.adapters.connectors.google.calendar.events.delete_event import (
    DeleteEventOperation,
)
from google_work_agent.adapters.connectors.google.calendar.events.get_event import GetEventOperation
from google_work_agent.adapters.connectors.google.calendar.events.list_events import (
    ListEventsOperation,
)
from google_work_agent.adapters.connectors.google.calendar.events.update_event import (
    UpdateEventOperation,
)
from google_work_agent.adapters.connectors.google.calendar.freebusy.query_freebusy import (
    QueryFreebusyOperation,
)
from google_work_agent.adapters.connectors.google.gmail.attachments.get_attachment import (
    GetAttachmentOperation,
)
from google_work_agent.adapters.connectors.google.gmail.drafts.create_draft import (
    CreateDraftOperation,
)
from google_work_agent.adapters.connectors.google.gmail.drafts.get_draft import GetDraftOperation
from google_work_agent.adapters.connectors.google.gmail.drafts.update_draft import (
    UpdateDraftOperation,
)
from google_work_agent.adapters.connectors.google.gmail.messages.get_message import (
    GetMessageOperation,
)
from google_work_agent.adapters.connectors.google.gmail.messages.send_message import (
    SendMessageOperation,
)
from google_work_agent.adapters.connectors.google.gmail.threads.get_thread import GetThreadOperation
from google_work_agent.adapters.connectors.google.gmail.threads.search_threads import (
    SearchThreadsOperation,
)
from google_work_agent.adapters.connectors.google.tasks.tasklists.list_tasklists import (
    ListTasklistsOperation,
)
from google_work_agent.adapters.connectors.google.tasks.tasks.create_task import CreateTaskOperation
from google_work_agent.adapters.connectors.google.tasks.tasks.delete_task import DeleteTaskOperation
from google_work_agent.adapters.connectors.google.tasks.tasks.get_task import GetTaskOperation
from google_work_agent.adapters.connectors.google.tasks.tasks.list_tasks import ListTasksOperation
from google_work_agent.adapters.connectors.google.tasks.tasks.update_task import UpdateTaskOperation
from google_work_agent.adapters.connectors.google.workspace.mcp_server import credential_provider


class _ProviderOperation(Protocol):
    tool_id: str

    def execute(
        self,
        state: credential_provider.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]: ...


_OPERATIONS: dict[str, _ProviderOperation] = {
    operation.tool_id: operation()
    for operation in (
        SearchThreadsOperation,
        GetThreadOperation,
        GetMessageOperation,
        GetAttachmentOperation,
        CreateDraftOperation,
        UpdateDraftOperation,
        GetDraftOperation,
        SendMessageOperation,
        ListTasklistsOperation,
        ListTasksOperation,
        GetTaskOperation,
        CreateTaskOperation,
        UpdateTaskOperation,
        DeleteTaskOperation,
        ListCalendarsOperation,
        ListEventsOperation,
        QueryFreebusyOperation,
        GetEventOperation,
        CreateEventOperation,
        UpdateEventOperation,
        DeleteEventOperation,
    )
}


def dispatch_tool(
    state: credential_provider.GoogleWorkspaceCredentialProvider,
    tool_id: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    operation = _OPERATIONS.get(tool_id)
    if operation is None:
        raise credential_provider._WorkspaceToolError("TOOL_NOT_AVAILABLE")
    return operation.execute(state, arguments)


def dispatch_internal_tool(
    state: credential_provider.GoogleWorkspaceCredentialProvider,
    tool_id: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    operation = _INTERNAL_OPERATIONS.get(tool_id)
    if operation is None:
        raise credential_provider._WorkspaceToolError("TOOL_NOT_AVAILABLE")
    return operation(state, arguments)


def has_operation(tool_id: str) -> bool:
    return tool_id in _OPERATIONS


def has_internal_operation(tool_id: str) -> bool:
    return tool_id in _INTERNAL_OPERATIONS


def _gmail_get_ui_thread_detail(
    state: credential_provider.GoogleWorkspaceCredentialProvider,
    arguments: dict[str, object],
) -> dict[str, object]:
    thread_id = credential_provider._text_argument(arguments, "thread_id", maximum=2048)
    thread_path = credential_provider.quote(thread_id, safe="")
    payload = credential_provider._google_api(
        state,
        f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_path}",
        {"format": "full"},
    )
    messages = credential_provider._object_list(payload.get("messages"))
    if not messages:
        raise credential_provider._WorkspaceToolError("NOT_FOUND")
    message = credential_provider._latest_gmail_message(messages)
    message_id = credential_provider._required_response_text(message, "id")
    headers = credential_provider._headers(message)
    sender_name, sender_email = credential_provider._email_identity(
        credential_provider._decoded_header(headers.get("from"))
    )
    recipients = credential_provider._email_addresses(
        credential_provider._decoded_header(headers.get("to"))
    )
    cc = credential_provider._email_addresses(
        credential_provider._decoded_header(headers.get("cc"))
    )
    return {
        "thread_id": thread_id,
        "message_id": message_id,
        "rfc822_message_id": credential_provider._optional_text(headers.get("message-id")),
        "sender_name": sender_name,
        "sender_email": sender_email,
        "recipients": list(recipients),
        "cc": list(cc),
        "subject": credential_provider._decoded_header(headers.get("subject")),
        "received_at": credential_provider._optional_text(headers.get("date"))
        or credential_provider._optional_text(message.get("internalDate")),
        "body": credential_provider._gmail_message_body(message),
        "attachments": credential_provider._gmail_attachment_metadata(message),
        "version": credential_provider._optional_text(payload.get("historyId")) or "",
    }


def _search_by_recovery_fingerprint(
    state: credential_provider.GoogleWorkspaceCredentialProvider,
    arguments: dict[str, object],
) -> dict[str, object]:
    resource_type = credential_provider._text_argument(arguments, "resource_type", maximum=64)
    fingerprint = credential_provider._text_argument(arguments, "recovery_fingerprint", maximum=512)
    marker = credential_provider._recovery_marker(fingerprint)
    search = _RECOVERY_SEARCHES.get(resource_type)
    if search is None:
        raise credential_provider._WorkspaceToolError("INVALID_ARGUMENT")
    return {"items": search(state, marker)}


def _search_gmail_drafts_by_marker(
    state: credential_provider.GoogleWorkspaceCredentialProvider, marker: str
) -> list[dict[str, object]]:
    payload = credential_provider._google_api(
        state,
        "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
        {"q": marker, "maxResults": "10"},
    )
    draft_ids = [
        credential_provider._required_response_text(item, "id")
        for item in credential_provider._object_list(payload.get("drafts"))
    ]
    if len(draft_ids) != 1:
        return [
            credential_provider._snapshot("gmail_draft", draft_id, None, (), None, {})
            for draft_id in draft_ids
        ]
    draft_path = credential_provider.quote(draft_ids[0], safe="")
    detail = credential_provider._google_api(
        state,
        f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{draft_path}",
        {"format": "metadata"},
    )
    return [credential_provider._gmail_draft_snapshot(detail)]


def _search_gmail_messages_by_marker(
    state: credential_provider.GoogleWorkspaceCredentialProvider, marker: str
) -> list[dict[str, object]]:
    payload = credential_provider._google_api(
        state,
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        {"q": marker, "maxResults": "10"},
    )
    message_ids = [
        credential_provider._required_response_text(item, "id")
        for item in credential_provider._object_list(payload.get("messages"))
    ]
    if len(message_ids) != 1:
        return [
            credential_provider._snapshot("gmail_message", message_id, None, (), None, {})
            for message_id in message_ids
        ]
    message_path = credential_provider.quote(message_ids[0], safe="")
    detail = credential_provider._google_api(
        state,
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_path}",
        {"format": "metadata"},
    )
    headers = credential_provider._headers(detail)
    return [
        credential_provider._snapshot(
            "gmail_message",
            message_ids[0],
            credential_provider._optional_text(detail.get("threadId")),
            (),
            detail.get("historyId"),
            {"subject": headers.get("subject", message_ids[0]), "sent": True},
        )
    ]


def _search_tasks_by_marker(
    state: credential_provider.GoogleWorkspaceCredentialProvider, marker: str
) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    task_lists = credential_provider._google_api(
        state,
        "https://tasks.googleapis.com/tasks/v1/users/@me/lists",
        {"maxResults": "100"},
    )
    for task_list in credential_provider._object_list(task_lists.get("items")):
        task_list_id = credential_provider._required_response_text(task_list, "id")
        task_list_path = credential_provider.quote(task_list_id, safe="")
        tasks = credential_provider._google_api(
            state,
            f"https://tasks.googleapis.com/tasks/v1/lists/{task_list_path}/tasks",
            {"maxResults": "100", "showHidden": "true"},
        )
        for item in credential_provider._object_list(tasks.get("items")):
            notes = credential_provider._optional_text(item.get("notes"))
            if notes and marker in notes:
                matches.append(credential_provider._task_snapshot(item, task_list_id))
    return matches


def _search_calendar_events_by_marker(
    state: credential_provider.GoogleWorkspaceCredentialProvider, marker: str
) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    calendars = credential_provider._google_api(
        state,
        "https://www.googleapis.com/calendar/v3/users/me/calendarList",
        {"maxResults": "100"},
    )
    for calendar in credential_provider._object_list(calendars.get("items")):
        calendar_id = credential_provider._required_response_text(calendar, "id")
        calendar_path = credential_provider.quote(calendar_id, safe="")
        events = credential_provider._google_api(
            state,
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_path}/events",
            {"q": marker, "maxResults": "10"},
        )
        for item in credential_provider._object_list(events.get("items")):
            matches.append(credential_provider._event_snapshot(item, calendar_id))
    return matches


type _InternalOperation = Callable[
    [credential_provider.GoogleWorkspaceCredentialProvider, dict[str, object]],
    dict[str, object],
]
type _RecoverySearch = Callable[
    [credential_provider.GoogleWorkspaceCredentialProvider, str],
    list[dict[str, object]],
]

_INTERNAL_OPERATIONS: dict[str, _InternalOperation] = {
    "gmail_get_ui_thread_detail": _gmail_get_ui_thread_detail,
    "search_by_recovery_fingerprint": _search_by_recovery_fingerprint,
}

_RECOVERY_SEARCHES: dict[str, _RecoverySearch] = {
    "gmail_draft": _search_gmail_drafts_by_marker,
    "gmail_message": _search_gmail_messages_by_marker,
    "task": _search_tasks_by_marker,
    "calendar_event": _search_calendar_events_by_marker,
}


__all__ = [
    "dispatch_internal_tool",
    "dispatch_tool",
    "has_internal_operation",
    "has_operation",
]
