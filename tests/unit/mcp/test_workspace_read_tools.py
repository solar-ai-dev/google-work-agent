from __future__ import annotations

from typing import cast

import pytest
from tests.support.fakes.mcp_transport import FakeMCPTransport

from google_work_agent.adapters.mcp import MCPGoogleWorkspaceGateway
from google_work_agent.mcp import server
from google_work_agent.mcp.settings import GoogleOAuthSettings
from google_work_agent.ports import TimeRange


def test_gmail_list_enriches_current_page_thread_metadata(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[str, dict[str, str] | None]] = []

    def google_api(
        _state: server._WorkspaceState, url: str, params: dict[str, str] | None = None
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
            {"format": "metadata"},
        ),
    ]


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


def test_gmail_detail_tool_contracts_are_unchanged(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    responses = [
        {
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
        },
        {
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
        },
    ]

    def google_api(
        _state: server._WorkspaceState, _url: str, _params: dict[str, str] | None = None
    ) -> dict[str, object]:
        return cast(dict[str, object], responses.pop(0))

    monkeypatch.setattr(server, "_google_api", google_api)

    thread = server._gmail_get_thread(_state(), {"thread_id": "thread-1"})
    message = server._gmail_get_message(_state(), {"message_id": "message-1"})

    assert cast(dict[str, object], cast(dict[str, object], thread["item"])["payload"]) == {
        "subject": "Project sync",
        "snippet": "Thread preview",
        "participants": ["pm@example.com", "user@example.com"],
        "message_ids": ["message-1"],
    }
    assert cast(dict[str, object], cast(dict[str, object], message["item"])["payload"]) == {
        "subject": "Project sync",
        "snippet": "Message preview",
        "from": "pm@example.com",
        "to": "user@example.com",
        "received_at": "Sat, 24 May 2025 09:15:00 +0900",
    }


def test_tasks_and_calendar_details_map_to_canonical_snapshots(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    responses = [
        {
            "id": "task-1",
            "title": "Follow up",
            "notes": "Call customer",
            "due": "2026-08-10T00:00:00.000Z",
            "status": "needsAction",
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
    assert cast(dict[str, object], task_item["payload"])["status"] == "needsAction"
    assert event_item["parent_id"] == "primary"
    assert cast(dict[str, object], event_item["payload"])["start"] == "2026-08-10T09:00:00+09:00"


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


def test_gateway_preserves_explicit_freebusy_range_in_mcp_arguments() -> None:
    transport = FakeMCPTransport()
    transport.queue_response({"calendars": []})

    MCPGoogleWorkspaceGateway(transport=transport).query_freebusy(
        calendar_ids=("primary",),
        time_range=TimeRange(
            start="2026-08-10T00:00:00+09:00",
            end="2026-08-11T00:00:00+09:00",
        ),
    )

    assert transport.call_log[0].arguments == {
        "calendar_ids": ["primary"],
        "time_min": "2026-08-10T00:00:00+09:00",
        "time_max": "2026-08-11T00:00:00+09:00",
    }


def _state() -> server._WorkspaceState:
    state = server._WorkspaceState(keyring=_MemorySecretStore())
    state.oauth_settings = GoogleOAuthSettings(
        google_oauth_client_id="desktop-client",
        google_oauth_client_secret="compatibility-client-secret",
    )
    return state


class _MemorySecretStore:
    def set_secret(self, *, service: str, account: str, secret: str) -> None:
        del service, account, secret

    def get_secret(self, *, service: str, account: str) -> str | None:
        del service, account
        return None

    def delete_secret(self, *, service: str, account: str) -> bool:
        del service, account
        return True
