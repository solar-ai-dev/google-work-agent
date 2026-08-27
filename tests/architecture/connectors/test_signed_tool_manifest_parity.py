from google_work_agent.application.tool_registry import load_signed_tool_registry


def test_signed_manifest_matches_current_canonical_google_workspace_rows() -> None:
    registry = load_signed_tool_registry()
    expected = {
        "gmail_search_threads",
        "gmail_get_thread",
        "gmail_get_message",
        "gmail_get_attachment",
        "gmail_create_draft",
        "gmail_update_draft",
        "gmail_get_draft",
        "gmail_send",
        "tasks_list_tasklists",
        "tasks_list_tasks",
        "tasks_get_task",
        "tasks_create_task",
        "tasks_update_task",
        "tasks_delete_task",
        "calendar_list_calendars",
        "calendar_list_events",
        "calendar_query_freebusy",
        "calendar_get_event",
        "calendar_create_event",
        "calendar_update_event",
        "calendar_delete_event",
    }

    assert {entry.tool_id for entry in registry.entries} == expected
