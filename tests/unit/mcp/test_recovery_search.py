"""Unit tests for WP3 UNKNOWN_RESULT recovery: fingerprint embedding + search."""

from __future__ import annotations

from typing import cast

import pytest

from google_work_agent.adapters.connectors.google.mcp import workspace_tools as server
from google_work_agent.adapters.connectors.google.mcp.oauth_settings import GoogleOAuthSettings

SESSION_KEY = "22" * 32
SERVICE_INSTANCE_ID = "svc-recovery-1"


def _state() -> server._WorkspaceState:
    state = server._WorkspaceState(keyring=_MemorySecretStore())
    state.oauth_settings = GoogleOAuthSettings(
        google_oauth_client_id="desktop-client",
        google_oauth_client_secret="compatibility-client-secret",
    )
    state.session_key = SESSION_KEY
    state.service_instance_id = SERVICE_INSTANCE_ID
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


def _build_claim(
    *, state: server._WorkspaceState, tool_name: str, execution_arguments: dict[str, object]
) -> dict[str, object]:
    issued_at_ms = server._now_ms()
    claim: dict[str, object] = {
        "claim_version": 2,
        "action_id": "action-1",
        "approval_id": "approval-1",
        "execution_attempt_id": "attempt-1",
        "tool_name": tool_name,
        "approval_arguments_hash": server._canonical_json_hash(execution_arguments),
        "execution_arguments_hash": server._canonical_json_hash(execution_arguments),
        "service_instance_id": state.service_instance_id,
        "mcp_process_instance_id": state.process_instance_id,
        "issued_at_ms": issued_at_ms,
        "expires_at_ms": issued_at_ms + 30_000,
        "nonce": "nonce-recovery-1",
    }
    claim["signature"] = server._sign_claim_context(state.session_key, claim)
    return claim


# --------------------------------------------------------------------------
# Marker embedding at CREATE / SEND time
# --------------------------------------------------------------------------


def test_gmail_create_draft_embeds_recovery_marker_in_body(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def google_api_call(
        _state: server._WorkspaceState,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        captured["body"] = body
        return {"id": "draft-1", "message": {"id": "msg-1", "threadId": "thread-1"}}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    payload: dict[str, object] = {
        "to": ["a@example.com"],
        "subject": "Hi",
        "body": "Body text",
        "recovery_fingerprint": "fp-create-1",
    }
    claim = _build_claim(
        state=state, tool_name="gmail_create_draft", execution_arguments={"payload": payload}
    )

    server._tool_call(
        state,
        tool_name="gmail_create_draft",
        arguments={"payload": payload, "claim_context": claim},
    )

    body = cast(dict[str, object], captured["body"])
    message = cast(dict[str, object], body["message"])
    raw_bytes = server._b64url_decode(cast(str, message["raw"]))
    assert server._recovery_marker("fp-create-1").encode("utf-8") in raw_bytes


def test_gmail_update_draft_never_embeds_a_marker(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def google_api_call(
        _state: server._WorkspaceState,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        captured["body"] = body
        return {"id": "draft-1", "message": {"id": "msg-1", "threadId": "thread-1"}}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body text"}
    claim = _build_claim(
        state=state,
        tool_name="gmail_update_draft",
        execution_arguments={"draft_id": "draft-1", "payload": payload},
    )

    server._tool_call(
        state,
        tool_name="gmail_update_draft",
        arguments={"draft_id": "draft-1", "payload": payload, "claim_context": claim},
    )

    body = cast(dict[str, object], captured["body"])
    message = cast(dict[str, object], body["message"])
    raw_bytes = server._b64url_decode(cast(str, message["raw"]))
    assert server.RECOVERY_MARKER_PREFIX.encode("utf-8") not in raw_bytes


def test_tasks_create_task_embeds_recovery_marker_in_notes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def google_api_call(
        _state: server._WorkspaceState,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        captured["body"] = body
        return {"id": "task-1", "title": "Follow up"}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    payload: dict[str, object] = {
        "title": "Follow up",
        "notes": "Call customer",
        "recovery_fingerprint": "fp-task-1",
    }
    claim = _build_claim(
        state=state,
        tool_name="tasks_create_task",
        execution_arguments={"task_list_id": "list-1", "payload": payload},
    )

    server._tool_call(
        state,
        tool_name="tasks_create_task",
        arguments={"task_list_id": "list-1", "payload": payload, "claim_context": claim},
    )

    body = cast(dict[str, object], captured["body"])
    notes = cast(str, body["notes"])
    assert notes.startswith("Call customer")
    assert server._recovery_marker("fp-task-1") in notes


def test_calendar_create_event_embeds_recovery_marker_in_description(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def google_api_call(
        _state: server._WorkspaceState,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        captured["body"] = body
        return {"id": "event-1", "summary": "Review"}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    payload: dict[str, object] = {
        "title": "Review",
        "start": "2026-08-10T09:00:00+09:00",
        "end": "2026-08-10T10:00:00+09:00",
        "recovery_fingerprint": "fp-event-1",
    }
    claim = _build_claim(
        state=state,
        tool_name="calendar_create_event",
        execution_arguments={"calendar_id": "primary", "payload": payload},
    )

    server._tool_call(
        state,
        tool_name="calendar_create_event",
        arguments={"calendar_id": "primary", "payload": payload, "claim_context": claim},
    )

    body = cast(dict[str, object], captured["body"])
    assert server._recovery_marker("fp-event-1") in cast(str, body["description"])


def test_gmail_send_rewrites_draft_with_marker_before_sending(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[str, str]] = []
    original_mime = server.EmailMessage()
    original_mime["To"] = "a@example.com"
    original_mime["Subject"] = "Hi"
    original_mime.set_content("Original body")
    encoded_raw = server._b64url_encode(original_mime.as_bytes())

    def google_api_call(
        _state: server._WorkspaceState,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append((method, url))
        if method == "GET":
            return {"message": {"raw": encoded_raw}}
        assert method == "PUT"
        message = cast(dict[str, object], cast(dict[str, object], body)["message"])
        raw_bytes = server._b64url_decode(cast(str, message["raw"]))
        assert b"Original body" in raw_bytes
        assert server._recovery_marker("fp-send-1").encode("utf-8") in raw_bytes
        return {"id": "draft-1", "message": {"id": "msg-1"}}

    def google_api_post(
        _state: server._WorkspaceState, url: str, body: dict[str, object]
    ) -> dict[str, object]:
        calls.append(("POST", url))
        assert body == {"id": "draft-1"}
        return {"id": "msg-sent-1", "threadId": "thread-1"}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    monkeypatch.setattr(server, "_google_api_post", google_api_post)
    state = _state()
    claim = _build_claim(
        state=state,
        tool_name="gmail_send",
        execution_arguments={"draft_id": "draft-1", "recovery_fingerprint": "fp-send-1"},
    )

    result = server._tool_call(
        state,
        tool_name="gmail_send",
        arguments={
            "draft_id": "draft-1",
            "recovery_fingerprint": "fp-send-1",
            "claim_context": claim,
        },
    )

    assert cast(dict[str, object], result["item"])["resource_id"] == "msg-sent-1"
    assert [call[0] for call in calls] == ["GET", "PUT", "POST"]


def test_gmail_send_without_fingerprint_never_touches_the_draft(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail_on_any_call(*_args: object, **_kwargs: object) -> dict[str, object]:
        pytest.fail("draft must not be re-read or rewritten when no fingerprint is supplied")

    def google_api_post(
        _state: server._WorkspaceState, url: str, body: dict[str, object]
    ) -> dict[str, object]:
        assert body == {"id": "draft-1"}
        return {"id": "msg-sent-1", "threadId": "thread-1"}

    monkeypatch.setattr(server, "_google_api_call", fail_on_any_call)
    monkeypatch.setattr(server, "_google_api_post", google_api_post)
    state = _state()
    claim = _build_claim(
        state=state,
        tool_name="gmail_send",
        execution_arguments={"draft_id": "draft-1", "recovery_fingerprint": None},
    )

    result = server._tool_call(
        state,
        tool_name="gmail_send",
        arguments={"draft_id": "draft-1", "recovery_fingerprint": None, "claim_context": claim},
    )

    assert cast(dict[str, object], result["item"])["resource_id"] == "msg-sent-1"


# --------------------------------------------------------------------------
# search_by_recovery_fingerprint
# --------------------------------------------------------------------------


def test_search_gmail_draft_returns_full_snapshot_for_a_single_match(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    responses = [
        {"drafts": [{"id": "draft-1"}]},
        {
            "id": "draft-1",
            "message": {
                "id": "msg-1",
                "threadId": "thread-1",
                "payload": {"headers": [{"name": "Subject", "value": "Hi"}]},
            },
        },
    ]

    def google_api(
        _state: server._WorkspaceState, url: str, params: dict[str, str] | None = None
    ) -> dict[str, object]:
        return cast(dict[str, object], responses.pop(0))

    monkeypatch.setattr(server, "_google_api", google_api)
    result = server._tool_call(
        _state(),
        tool_name="search_by_recovery_fingerprint",
        arguments={"resource_type": "gmail_draft", "recovery_fingerprint": "fp-1"},
    )
    items = cast(list[dict[str, object]], result["items"])
    assert len(items) == 1
    assert items[0]["resource_id"] == "draft-1"


def test_search_gmail_draft_returns_no_candidates_when_zero_matches(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(server, "_google_api", lambda *a, **k: {"drafts": []})
    result = server._tool_call(
        _state(),
        tool_name="search_by_recovery_fingerprint",
        arguments={"resource_type": "gmail_draft", "recovery_fingerprint": "fp-missing"},
    )
    assert result["items"] == []


def test_search_gmail_draft_returns_all_candidates_when_ambiguous(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        server, "_google_api", lambda *a, **k: {"drafts": [{"id": "d1"}, {"id": "d2"}]}
    )
    result = server._tool_call(
        _state(),
        tool_name="search_by_recovery_fingerprint",
        arguments={"resource_type": "gmail_draft", "recovery_fingerprint": "fp-dup"},
    )
    items = cast(list[dict[str, object]], result["items"])
    assert {item["resource_id"] for item in items} == {"d1", "d2"}


def test_search_gmail_message_returns_full_snapshot_for_a_single_match(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    responses = [
        {"messages": [{"id": "msg-1"}]},
        {
            "id": "msg-1",
            "threadId": "thread-1",
            "historyId": "5",
            "payload": {"headers": [{"name": "Subject", "value": "Sent"}]},
        },
    ]

    def google_api(
        _state: server._WorkspaceState, url: str, params: dict[str, str] | None = None
    ) -> dict[str, object]:
        return cast(dict[str, object], responses.pop(0))

    monkeypatch.setattr(server, "_google_api", google_api)
    result = server._tool_call(
        _state(),
        tool_name="search_by_recovery_fingerprint",
        arguments={"resource_type": "gmail_message", "recovery_fingerprint": "fp-send-1"},
    )
    items = cast(list[dict[str, object]], result["items"])
    assert items[0]["resource_id"] == "msg-1"
    assert items[0]["payload"] == {"subject": "Sent", "sent": True}


def test_search_tasks_scans_all_task_lists_and_filters_by_marker(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    marker = server._recovery_marker("fp-task-1")
    responses = {
        "https://tasks.googleapis.com/tasks/v1/users/@me/lists": {
            "items": [{"id": "list-1"}, {"id": "list-2"}]
        },
        "https://tasks.googleapis.com/tasks/v1/lists/list-1/tasks": {
            "items": [
                {"id": "task-1", "title": "Match", "notes": f"context\n\n{marker}"},
                {"id": "task-2", "title": "No match", "notes": "unrelated"},
            ]
        },
        "https://tasks.googleapis.com/tasks/v1/lists/list-2/tasks": {"items": []},
    }

    def google_api(
        _state: server._WorkspaceState, url: str, params: dict[str, str] | None = None
    ) -> dict[str, object]:
        return responses[url]

    monkeypatch.setattr(server, "_google_api", google_api)
    result = server._tool_call(
        _state(),
        tool_name="search_by_recovery_fingerprint",
        arguments={"resource_type": "task", "recovery_fingerprint": "fp-task-1"},
    )
    items = cast(list[dict[str, object]], result["items"])
    assert len(items) == 1
    assert items[0]["resource_id"] == "task-1"
    assert items[0]["parent_id"] == "list-1"


def test_search_calendar_events_scans_all_calendars_with_query(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    responses = {
        "https://www.googleapis.com/calendar/v3/users/me/calendarList": {
            "items": [{"id": "primary"}, {"id": "team"}]
        },
        "https://www.googleapis.com/calendar/v3/calendars/primary/events": {
            "items": [{"id": "event-1", "summary": "Review"}]
        },
        "https://www.googleapis.com/calendar/v3/calendars/team/events": {"items": []},
    }

    def google_api(
        _state: server._WorkspaceState, url: str, params: dict[str, str] | None = None
    ) -> dict[str, object]:
        if url.endswith("/events"):
            assert params is not None and "q" in params
        return responses[url]

    monkeypatch.setattr(server, "_google_api", google_api)
    result = server._tool_call(
        _state(),
        tool_name="search_by_recovery_fingerprint",
        arguments={"resource_type": "calendar_event", "recovery_fingerprint": "fp-event-1"},
    )
    items = cast(list[dict[str, object]], result["items"])
    assert len(items) == 1
    assert items[0]["resource_id"] == "event-1"
    assert items[0]["parent_id"] == "primary"


def test_search_by_recovery_fingerprint_rejects_unknown_resource_type(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(server, "_google_api", lambda *a, **k: pytest.fail("must not call Google"))
    with pytest.raises(server._WorkspaceToolError) as exc_info:
        server._tool_call(
            _state(),
            tool_name="search_by_recovery_fingerprint",
            arguments={"resource_type": "task_list", "recovery_fingerprint": "fp-1"},
        )
    assert exc_info.value.safe_code == "INVALID_ARGUMENT"
