"""Dispatch one validated Google Workspace MCP tool operation."""

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
from google_work_agent.adapters.connectors.google.workspace.mcp_server import workspace_runtime

_OPERATIONS = {
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
    state: workspace_runtime._WorkspaceState,
    tool_id: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    operation = _OPERATIONS.get(tool_id)
    if operation is None:
        raise workspace_runtime._WorkspaceToolError("TOOL_NOT_AVAILABLE")
    return operation.execute(state, arguments)


__all__ = ["dispatch_tool"]
