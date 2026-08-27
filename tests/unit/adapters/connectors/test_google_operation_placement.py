"""Repository-contract tests for canonical Google connector operation placement."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    ("module_name", "symbol"),
    [
        (
            "google_work_agent.adapters.connectors.google.gmail.threads.search_threads",
            "SearchThreadsOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.gmail.threads.get_thread",
            "GetThreadOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.gmail.messages.get_message",
            "GetMessageOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.gmail.attachments.get_attachment",
            "GetAttachmentOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.gmail.messages.send_message",
            "SendMessageOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.gmail.drafts.get_draft",
            "GetDraftOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.gmail.drafts.create_draft",
            "CreateDraftOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.gmail.drafts.update_draft",
            "UpdateDraftOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.tasks.tasklists.list_tasklists",
            "ListTasklistsOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.tasks.tasks.list_tasks",
            "ListTasksOperation",
        ),
        ("google_work_agent.adapters.connectors.google.tasks.tasks.get_task", "GetTaskOperation"),
        (
            "google_work_agent.adapters.connectors.google.tasks.tasks.create_task",
            "CreateTaskOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.tasks.tasks.update_task",
            "UpdateTaskOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.tasks.tasks.delete_task",
            "DeleteTaskOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.calendar.calendars.list_calendars",
            "ListCalendarsOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.calendar.events.list_events",
            "ListEventsOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.calendar.events.get_event",
            "GetEventOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.calendar.events.create_event",
            "CreateEventOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.calendar.events.update_event",
            "UpdateEventOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.calendar.events.delete_event",
            "DeleteEventOperation",
        ),
        (
            "google_work_agent.adapters.connectors.google.calendar.freebusy.query_freebusy",
            "QueryFreebusyOperation",
        ),
    ],
)
def test_canonical_operation_module_exposes_exact_operation_symbol(
    module_name: str, symbol: str
) -> None:
    module = importlib.import_module(module_name)
    assert getattr(module, symbol).__module__ == module_name
