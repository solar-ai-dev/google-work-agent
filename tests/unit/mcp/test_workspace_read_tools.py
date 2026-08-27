from __future__ import annotations

import base64
from typing import cast

import pytest

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    workspace_runtime as server,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server.oauth_settings import (
    GoogleOAuthSettings,
)


def test_gmail_list_enriches_current_page_thread_metadata(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[str, dict[str, str | list[str]] | None]] = []

    def google_api(
        _state: server._WorkspaceState, url: str, params: dict[str, str | list[str]] | None = None
    ) -> dict[str, object]:
        calls.append((url, params))
        if url.endswith("/threads/thread-1"):
            return {
                "historyId": "8",
                "snippet": "Detail preview",
                "messages": [
                    {
                        "id": "message-1",
                        "internalDate": "1748055300000",
                        "payload": {
                            "headers": [
                                {"name": "From", "value": "Kim Daeri <kim.daeri@example.com>"},
                                {"name": "Subject", "value": "Q2 campaign follow-up"},
                                {"name": "Date", "value": "Sat, 24 May 2025 09:15:00 +0900"},
                            ]
                        },
                    }
                ],
            }
        return {
            "threads": [{"id": "thread-1", "historyId": "7", "snippet": "Preview"}],
            "nextPageToken": "next-1",
        }

    monkeypatch.setattr(server, "_google_api", google_api)

    payload = server._tool_call(
        _state(),
        tool_name="gmail_search_threads",
        arguments={"query": "label:inbox", "page_size": 20, "page_token": None},
    )

    assert payload["next_page_token"] == "next-1"
    assert payload["items"] == [
        {
            "fixture_snapshot_id": "thread-1",
            "resource_type": "gmail_thread",
            "resource_id": "thread-1",
            "parent_id": None,
            "related_resource_ids": [],
            "version": "7",
            "recovery_fingerprint": None,
            "payload": {
                "sender_name": "Kim Daeri",
                "sender_email": "kim.daeri@example.com",
                "subject": "Q2 campaign follow-up",
                "received_at": "Sat, 24 May 2025 09:15:00 +0900",
                "snippet": "Preview",
            },
        }
    ]
    assert calls == [
        (
            "https://gmail.googleapis.com/gmail/v1/users/me/threads",
            {"maxResults": "20", "q": "label:inbox"},
        ),
        (
            "https://gmail.googleapis.com/gmail/v1/users/me/threads/thread-1",
            {
                "format": "metadata",
                "metadataHeaders": ["From", "Subject", "Date"],
                "fields": "messages(internalDate,payload/headers),snippet",
            },
        ),
    ]


def test_gmail_metadata_hydration_uses_three_workers_and_preserves_provider_order(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    thread_ids = [f"thread-{index}" for index in range(20)]

    def google_api(
        _state: server._WorkspaceState, _url: str, _params: dict[str, str | list[str]] | None = None
    ) -> dict[str, object]:
        return {
            "threads": [
                {"id": thread_id, "historyId": str(index)}
                for index, thread_id in enumerate(thread_ids)
            ]
        }

    def metadata(
        *, state: server._WorkspaceState, thread_id: str, list_snippet: str | None
    ) -> dict[str, object]:
        del state, list_snippet
        return {"subject": f"Subject {thread_id}"}

    monkeypatch.setattr(server, "_google_api", google_api)
    monkeypatch.setattr(server, "_gmail_thread_list_metadata", metadata)

    payload = server._tool_call(
        _state(),
        tool_name="gmail_search_threads",
        arguments={"query": "label:inbox", "page_size": 20, "page_token": None},
    )

    items = cast(list[dict[str, object]], payload["items"])
    assert server.GMAIL_METADATA_HYDRATION_MAX_WORKERS == 3
    assert [item["resource_id"] for item in items] == thread_ids
    assert [cast(dict[str, object], item["payload"])["subject"] for item in items] == [
        f"Subject {thread_id}" for thread_id in thread_ids
    ]


def test_gmail_metadata_hydration_failure_fails_the_whole_page(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def google_api(
        _state: server._WorkspaceState, _url: str, _params: dict[str, str | list[str]] | None = None
    ) -> dict[str, object]:
        return {"threads": [{"id": "thread-1"}, {"id": "thread-2"}]}

    def metadata(
        *, state: server._WorkspaceState, thread_id: str, list_snippet: str | None
    ) -> dict[str, object]:
        del state, list_snippet
        if thread_id == "thread-2":
            raise server._WorkspaceToolError("TIMEOUT")
        return {"subject": "First"}

    monkeypatch.setattr(server, "_google_api", google_api)
    monkeypatch.setattr(server, "_gmail_thread_list_metadata", metadata)

    with pytest.raises(server._WorkspaceToolError, match="TIMEOUT"):
        server._tool_call(
            _state(),
            tool_name="gmail_search_threads",
            arguments={"query": "label:inbox", "page_size": 20, "page_token": None},
        )


def test_gmail_list_does_not_use_thread_id_as_subject_fallback(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def google_api(
        _state: server._WorkspaceState, url: str, _params: dict[str, str] | None = None
    ) -> dict[str, object]:
        if url.endswith("/threads/thread-1"):
            return {"messages": [{"id": "message-1", "payload": {"headers": []}}]}
        return {"threads": [{"id": "thread-1", "historyId": "7"}]}

    monkeypatch.setattr(server, "_google_api", google_api)

    payload = server._tool_call(
        _state(),
        tool_name="gmail_search_threads",
        arguments={"query": "", "page_size": 20, "page_token": None},
    )

    item = cast(dict[str, object], cast(list[object], payload["items"])[0])
    assert item["resource_id"] == "thread-1"
    assert item["payload"] == {}


def test_gmail_count_traversal_skips_per_thread_metadata_hydration(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[str, dict[str, str] | None]] = []

    def google_api(
        _state: server._WorkspaceState, url: str, _params: dict[str, str] | None = None
    ) -> dict[str, object]:
        calls.append((url, _params))
        return {"threads": [{"id": "thread-1", "historyId": "7", "snippet": "Preview"}]}

    monkeypatch.setattr(server, "_google_api", google_api)

    payload = server._tool_call(
        _state(),
        tool_name="gmail_search_threads",
        arguments={
            "query": "in:inbox category:primary",
            "page_size": 100,
            "page_token": None,
            "include_thread_metadata": False,
        },
    )

    assert calls == [
        (
            "https://gmail.googleapis.com/gmail/v1/users/me/threads",
            {
                "maxResults": "100",
                "q": "in:inbox category:primary",
                "fields": "threads/id,nextPageToken",
            },
        )
    ]
    assert cast(dict[str, object], cast(list[object], payload["items"])[0])["payload"] == {}


def test_gmail_thread_detail_tool_contract_is_unchanged(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def google_api(
        _state: server._WorkspaceState, _url: str, params: dict[str, str] | None = None
    ) -> dict[str, object]:
        assert params == {"format": "metadata"}
        return {
            "historyId": "9",
            "snippet": "Thread preview",
            "messages": [
                {
                    "id": "message-1",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "pm@example.com"},
                            {"name": "To", "value": "user@example.com"},
                            {"name": "Subject", "value": "Project sync"},
                        ]
                    },
                }
            ],
        }

    monkeypatch.setattr(server, "_google_api", google_api)

    thread = server._gmail_get_thread(_state(), {"thread_id": "thread-1"})

    assert cast(dict[str, object], cast(dict[str, object], thread["item"])["payload"]) == {
        "subject": "Project sync",
        "snippet": "Thread preview",
        "participants": ["pm@example.com", "user@example.com"],
        "message_ids": ["message-1"],
    }


def test_gmail_message_detail_fetches_full_format_and_includes_body(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """GAP-F6: Agent Retrieval reads the message body through this tool, so it
    must request ``format=full`` (not ``metadata``) and extract real body text
    -- the same extraction the Sidebar UI detail endpoint already used."""

    def google_api(
        _state: server._WorkspaceState, _url: str, params: dict[str, str] | None = None
    ) -> dict[str, object]:
        assert params == {"format": "full"}
        message = _gmail_message(
            "message-1",
            "2000",
            "Actual message body",
            parts=[
                {
                    "mimeType": "application/pdf",
                    "filename": "report.pdf",
                    "body": {"attachmentId": "attachment-1", "size": 2048},
                }
            ],
        )
        message["threadId"] = "thread-1"
        message["historyId"] = "10"
        message["snippet"] = "Message preview"
        return message

    monkeypatch.setattr(server, "_google_api", google_api)

    message = server._gmail_get_message(_state(), {"message_id": "message-1"})

    assert cast(dict[str, object], cast(dict[str, object], message["item"])["payload"]) == {
        "subject": "Project update",
        "snippet": "Message preview",
        "from": "Kim Daeri <kim.daeri@example.com>",
        "to": "User <user@example.com>",
        "received_at": "Mon, 10 Aug 2026 09:15:00 +0900",
        "body": "Actual message body",
        "attachments": [
            {
                "message_id": "message-1",
                "attachment_id": "attachment-1",
                "filename": "report.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 2048,
            }
        ],
    }
    assert cast(dict[str, object], message["item"])["parent_id"] == "thread-1"


def test_gmail_message_detail_omits_body_and_attachments_when_absent(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def google_api(
        _state: server._WorkspaceState, _url: str, _params: dict[str, str] | None = None
    ) -> dict[str, object]:
        return {
            "id": "message-1",
            "threadId": "thread-1",
            "historyId": "10",
            "snippet": "Message preview",
            "payload": {
                "headers": [
                    {"name": "From", "value": "pm@example.com"},
                    {"name": "To", "value": "user@example.com"},
                    {"name": "Subject", "value": "Project sync"},
                    {"name": "Date", "value": "Sat, 24 May 2025 09:15:00 +0900"},
                ]
            },
        }

    monkeypatch.setattr(server, "_google_api", google_api)

    message = server._gmail_get_message(_state(), {"message_id": "message-1"})

    assert cast(dict[str, object], cast(dict[str, object], message["item"])["payload"]) == {
        "subject": "Project sync",
        "snippet": "Message preview",
        "from": "pm@example.com",
        "to": "user@example.com",
        "received_at": "Sat, 24 May 2025 09:15:00 +0900",
        "attachments": [],
    }


def test_gmail_ui_detail_uses_latest_message_and_plain_body(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def google_api(
        _state: server._WorkspaceState, _url: str, params: dict[str, str] | None = None
    ) -> dict[str, object]:
        assert params == {"format": "full"}
        return {
            "historyId": "12",
            "messages": [
                _gmail_message("message-old", "1000", "Old body"),
                _gmail_message(
                    "message-new",
                    "2000",
                    "Latest body",
                    parts=[
                        {
                            "mimeType": "application/pdf",
                            "filename": "report.pdf",
                            "body": {"attachmentId": "attachment-1", "size": 2048},
                        }
                    ],
                ),
            ],
        }

    monkeypatch.setattr(server, "_google_api", google_api)

    detail = server._tool_call(
        _state(),
        tool_name="gmail_get_ui_thread_detail",
        arguments={"thread_id": "thread-1"},
    )

    assert detail == {
        "thread_id": "thread-1",
        "message_id": "message-new",
        "rfc822_message_id": "<msg-id@example.com>",
        "sender_name": "Kim Daeri",
        "sender_email": "kim.daeri@example.com",
        "recipients": ["User <user@example.com>"],
        "cc": ["team@example.com"],
        "subject": "Project update",
        "received_at": "Mon, 10 Aug 2026 09:15:00 +0900",
        "body": "Latest body",
        "attachments": [
            {
                "message_id": "message-new",
                "attachment_id": "attachment-1",
                "filename": "report.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 2048,
            }
        ],
        "version": "12",
    }


def test_gmail_ui_detail_converts_nested_html_when_plain_is_missing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    html = (
        "<html><style>hidden</style><body><p>Hello <strong>team</strong>.</p>"
        "<script>bad()</script><div>Next line</div></body></html>"
    )
    message = _gmail_message("message-1", "2000", None)
    cast(dict[str, object], message["payload"])["mimeType"] = "multipart/mixed"
    cast(dict[str, object], message["payload"])["body"] = {}
    cast(dict[str, object], message["payload"])["parts"] = [
        {
            "mimeType": "multipart/alternative",
            "body": {},
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": _gmail_b64(html)},
                }
            ],
        }
    ]

    monkeypatch.setattr(server, "_google_api", lambda *_args, **_kwargs: {"messages": [message]})

    detail = server._gmail_get_ui_thread_detail(_state(), {"thread_id": "thread-1"})

    assert detail["body"] == "Hello team.\nNext line"
    assert "hidden" not in str(detail["body"])
    assert "bad" not in str(detail["body"])


def test_gmail_ui_detail_allows_missing_or_malformed_body(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    message = _gmail_message("message-1", "2000", None)
    cast(dict[str, object], message["payload"])["body"] = {"data": "%%%"}
    monkeypatch.setattr(server, "_google_api", lambda *_args, **_kwargs: {"messages": [message]})

    detail = server._gmail_get_ui_thread_detail(_state(), {"thread_id": "thread-1"})

    assert "body" not in detail or detail["body"] is None


def test_gmail_ui_detail_omits_rfc822_message_id_when_header_is_absent(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    message = _gmail_message("message-1", "2000", "Body")
    headers = cast(list[dict[str, object]], cast(dict[str, object], message["payload"])["headers"])
    cast(dict[str, object], message["payload"])["headers"] = [
        header for header in headers if header["name"] != "Message-ID"
    ]
    monkeypatch.setattr(server, "_google_api", lambda *_args, **_kwargs: {"messages": [message]})

    detail = server._gmail_get_ui_thread_detail(_state(), {"thread_id": "thread-1"})

    assert detail["rfc822_message_id"] is None


def _gmail_message(
    message_id: str,
    internal_date: str,
    body: str | None,
    *,
    parts: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "mimeType": "text/plain",
        "headers": [
            {"name": "From", "value": "Kim Daeri <kim.daeri@example.com>"},
            {"name": "To", "value": "User <user@example.com>"},
            {"name": "Cc", "value": "team@example.com"},
            {"name": "Subject", "value": "Project update"},
            {"name": "Date", "value": "Mon, 10 Aug 2026 09:15:00 +0900"},
            {"name": "Message-ID", "value": "<msg-id@example.com>"},
        ],
        "body": {"data": _gmail_b64(body)} if body is not None else {},
    }
    if parts:
        payload["parts"] = parts
    return {"id": message_id, "internalDate": internal_date, "payload": payload}


def _gmail_b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def test_tasks_and_calendar_details_map_to_canonical_snapshots(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    responses = [
        {
            "id": "task-1",
            "title": "Follow up",
            "notes": "Call customer",
            "due": "2026-08-10T00:00:00.000Z",
            "status": "needsAction",
            "completed": "2026-08-13T00:30:00.000Z",
            "updated": "2026-08-09T00:00:00.000Z",
        },
        {
            "id": "event-1",
            "summary": "Review",
            "status": "confirmed",
            "etag": "etag-1",
            "start": {"dateTime": "2026-08-10T09:00:00+09:00"},
            "end": {"dateTime": "2026-08-10T10:00:00+09:00"},
        },
    ]

    def google_api(
        _state: server._WorkspaceState, _url: str, _params: dict[str, str] | None = None
    ) -> dict[str, object]:
        return cast(dict[str, object], responses.pop(0))

    monkeypatch.setattr(server, "_google_api", google_api)
    state = _state()

    task = server._tool_call(
        state,
        tool_name="tasks_get_task",
        arguments={"task_list_id": "list-1", "task_id": "task-1"},
    )
    event = server._tool_call(
        state,
        tool_name="calendar_get_event",
        arguments={"calendar_id": "primary", "event_id": "event-1"},
    )

    task_item = cast(dict[str, object], task["item"])
    event_item = cast(dict[str, object], event["item"])
    assert task_item["parent_id"] == "list-1"
    assert cast(dict[str, object], task_item["payload"])["title"] == "Follow up"
    assert cast(dict[str, object], task_item["payload"])["status"] == "needsAction"
    assert cast(dict[str, object], task_item["payload"])["completed"] == "2026-08-13T00:30:00.000Z"
    assert event_item["parent_id"] == "primary"
    assert cast(dict[str, object], event_item["payload"])["start"] == "2026-08-10T09:00:00+09:00"


def test_calendar_event_list_expands_recurring_events_and_preserves_all_day_dates(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def google_api(
        _state: server._WorkspaceState,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, object]:
        captured["url"] = url
        captured["params"] = params
        return {
            "items": [
                {
                    "id": "recurring-instance-1",
                    "summary": "Daily stand-up",
                    "start": {"dateTime": "2026-08-10T09:00:00+09:00"},
                    "end": {"dateTime": "2026-08-10T09:30:00+09:00"},
                    "recurringEventId": "recurring-series-1",
                    "attendees": [
                        {"email": "other@example.com", "responseStatus": "accepted"},
                        {
                            "email": "me@example.com",
                            "self": True,
                            "responseStatus": "tentative",
                        },
                    ],
                },
                {
                    "id": "all-day-1",
                    "summary": "Company day",
                    "start": {"date": "2026-08-11"},
                    "end": {"date": "2026-08-12"},
                },
            ],
            "nextPageToken": "events-page-2",
        }

    monkeypatch.setattr(server, "_google_api", google_api)

    result = server._calendar_list_events(
        _state(),
        {
            "calendar_id": "work@example.com",
            "time_min": "2026-08-10T00:00:00Z",
            "time_max": "2026-11-08T00:00:00Z",
            "single_events": True,
            "order_by": "startTime",
            "page_size": 10,
            "page_token": "events-page-1",
        },
    )

    assert captured == {
        "url": "https://www.googleapis.com/calendar/v3/calendars/work%40example.com/events",
        "params": {
            "maxResults": "10",
            "pageToken": "events-page-1",
            "timeMin": "2026-08-10T00:00:00Z",
            "timeMax": "2026-11-08T00:00:00Z",
            "singleEvents": "true",
            "orderBy": "startTime",
        },
    }
    items = cast(list[dict[str, object]], result["items"])
    recurring_payload = cast(dict[str, object], items[0]["payload"])
    all_day_payload = cast(dict[str, object], items[1]["payload"])
    assert recurring_payload["title"] == "Daily stand-up"
    assert recurring_payload["start"] == "2026-08-10T09:00:00+09:00"
    assert recurring_payload["end"] == "2026-08-10T09:30:00+09:00"
    assert recurring_payload["self_response_status"] == "tentative"
    assert all_day_payload["start"] == "2026-08-11"
    assert all_day_payload["end"] == "2026-08-12"
    assert result["next_page_token"] == "events-page-2"


def test_event_snapshot_preserves_resource_id_as_the_untitled_event_fallback() -> None:
    snapshot = server._event_snapshot(
        {
            "id": "untitled-event-1",
            "start": {"date": "2026-08-11"},
            "end": {"date": "2026-08-12"},
        },
        "primary",
    )

    payload = cast(dict[str, object], snapshot["payload"])
    assert snapshot["resource_id"] == "untitled-event-1"
    assert payload["title"] == "untitled-event-1"


def test_read_tool_input_rejects_invalid_page_token(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(server, "_google_api", lambda *_args, **_kwargs: {})

    try:
        server._tool_call(
            _state(),
            tool_name="gmail_search_threads",
            arguments={"query": "", "page_size": 20, "page_token": "bad\nvalue"},
        )
    except server._WorkspaceToolError as error:
        assert error.safe_code == "INVALID_ARGUMENT"
    else:
        raise AssertionError("invalid page token must be rejected")


def test_freebusy_maps_explicit_range_to_google_request(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def google_api_post(
        _state: server._WorkspaceState, url: str, body: dict[str, object]
    ) -> dict[str, object]:
        captured["url"] = url
        captured["body"] = body
        return {
            "calendars": {
                "primary": {
                    "busy": [
                        {
                            "start": "2026-08-10T09:00:00+09:00",
                            "end": "2026-08-10T10:00:00+09:00",
                        }
                    ]
                }
            }
        }

    monkeypatch.setattr(server, "_google_api_post", google_api_post)

    payload = server._calendar_query_freebusy(
        _state(),
        {
            "calendar_ids": ["primary"],
            "time_min": "2026-08-10T00:00:00+09:00",
            "time_max": "2026-08-11T00:00:00+09:00",
        },
    )

    assert captured == {
        "url": "https://www.googleapis.com/calendar/v3/freeBusy",
        "body": {
            "timeMin": "2026-08-10T00:00:00+09:00",
            "timeMax": "2026-08-11T00:00:00+09:00",
            "items": [{"id": "primary"}],
        },
    }
    calendars = cast(list[dict[str, object]], payload["calendars"])
    intervals = cast(list[dict[str, object]], calendars[0]["intervals"])
    assert intervals[0]["transparency"] == "busy"


def test_freebusy_rejects_invalid_range_without_google_request(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        server,
        "_google_api_post",
        lambda *_args, **_kwargs: pytest.fail("Google API must not be called"),
    )

    with pytest.raises(server._WorkspaceToolError, match="INVALID_ARGUMENT"):
        server._calendar_query_freebusy(
            _state(),
            {
                "calendar_ids": ["primary"],
                "time_min": "2026-08-11T00:00:00+09:00",
                "time_max": "2026-08-10T00:00:00+09:00",
            },
        )


def _state() -> server._WorkspaceState:
    state = server._WorkspaceState(keyring=_MemorySecretStorePort())
    state.oauth_settings = GoogleOAuthSettings(
        google_oauth_client_id="desktop-client",
        google_oauth_client_secret="compatibility-client-secret",
    )
    return state


class _MemorySecretStorePort:
    def put(self, key: str, secret_bytes: bytes) -> None:
        del key, secret_bytes

    def get(self, key: str) -> bytes | None:
        del key
        return None

    def delete(self, key: str) -> None:
        del key
