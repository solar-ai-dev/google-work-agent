"""Unit tests for R8.4 ClaimContextV2 validation and Gmail write/read tools."""

from __future__ import annotations

from typing import cast

import pytest

from google_work_agent.domain import calculate_canonical_json_hash
from google_work_agent.mcp import server
from google_work_agent.mcp.settings import GoogleOAuthSettings

SESSION_KEY = "11" * 32
SERVICE_INSTANCE_ID = "svc-test-1"


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
    *,
    state: server._WorkspaceState,
    tool_name: str,
    execution_arguments: dict[str, object],
    action_id: str = "action-1",
    approval_id: str = "approval-1",
    execution_attempt_id: str = "attempt-1",
    service_instance_id: str | None = None,
    mcp_process_instance_id: str | None = None,
    nonce: str = "nonce-1",
    ttl_ms: int = 30_000,
    issued_offset_ms: int = 0,
    execution_arguments_hash: str | None = None,
) -> dict[str, object]:
    issued_at_ms = server._now_ms() + issued_offset_ms
    claim: dict[str, object] = {
        "claim_version": 2,
        "action_id": action_id,
        "approval_id": approval_id,
        "execution_attempt_id": execution_attempt_id,
        "tool_name": tool_name,
        "approval_arguments_hash": calculate_canonical_json_hash(execution_arguments),
        "execution_arguments_hash": (
            execution_arguments_hash
            if execution_arguments_hash is not None
            else calculate_canonical_json_hash(execution_arguments)
        ),
        "service_instance_id": service_instance_id or state.service_instance_id,
        "mcp_process_instance_id": mcp_process_instance_id or state.process_instance_id,
        "issued_at_ms": issued_at_ms,
        "expires_at_ms": issued_at_ms + ttl_ms,
        "nonce": nonce,
    }
    claim["signature"] = server._sign_claim_context(state.session_key, claim)
    return claim


def _reject_google_calls(*_args: object, **_kwargs: object) -> dict[str, object]:
    pytest.fail("Google API must not be called")


# --------------------------------------------------------------------------
# Happy-path dispatch
# --------------------------------------------------------------------------


def test_gmail_create_draft_dispatches_with_valid_claim(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def google_api_call(
        _state: server._WorkspaceState,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append((method, url, body))
        return {
            "id": "draft-1",
            "message": {
                "id": "msg-1",
                "threadId": "thread-1",
                "historyId": "10",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Hi"},
                        {"name": "To", "value": "a@example.com"},
                    ]
                },
            },
        }

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body text"}
    claim = _build_claim(
        state=state, tool_name="gmail_create_draft", execution_arguments={"payload": payload}
    )

    result = server._tool_call(
        state,
        tool_name="gmail_create_draft",
        arguments={"payload": payload, "claim_context": claim},
    )

    item = cast(dict[str, object], result["item"])
    assert item["resource_id"] == "draft-1"
    assert item["resource_type"] == "gmail_draft"
    assert len(calls) == 1
    assert calls[0][0] == "POST"
    assert calls[0][1] == "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
    body = cast(dict[str, object], calls[0][2])
    message = cast(dict[str, object], body["message"])
    assert "raw" in message


def test_gmail_update_draft_dispatches_with_valid_claim(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def google_api_call(
        _state: server._WorkspaceState,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append(method)
        return {"id": "draft-1", "message": {"id": "msg-1", "threadId": "thread-1"}}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Updated", "body": "New body"}
    claim = _build_claim(
        state=state,
        tool_name="gmail_update_draft",
        execution_arguments={"draft_id": "draft-1", "payload": payload},
    )

    result = server._tool_call(
        state,
        tool_name="gmail_update_draft",
        arguments={"draft_id": "draft-1", "payload": payload, "claim_context": claim},
    )

    assert cast(dict[str, object], result["item"])["resource_id"] == "draft-1"
    assert calls == ["PUT"]


def test_gmail_send_dispatches_with_valid_claim(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[str, dict[str, object]]] = []

    def google_api_post(
        _state: server._WorkspaceState, url: str, body: dict[str, object]
    ) -> dict[str, object]:
        calls.append((url, body))
        return {
            "id": "msg-sent-1",
            "threadId": "thread-1",
            "historyId": "20",
            "payload": {"headers": [{"name": "Subject", "value": "Hi"}]},
        }

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

    item = cast(dict[str, object], result["item"])
    assert item["resource_id"] == "msg-sent-1"
    assert item["resource_type"] == "gmail_message"
    assert len(calls) == 1
    assert calls[0][0] == "https://gmail.googleapis.com/gmail/v1/users/me/drafts/send"
    assert calls[0][1] == {"id": "draft-1"}


def test_gmail_get_draft_reads_without_a_claim(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def google_api(
        _state: server._WorkspaceState, url: str, params: dict[str, str] | None = None
    ) -> dict[str, object]:
        assert url.endswith("/drafts/draft-1")
        return {
            "id": "draft-1",
            "message": {
                "id": "msg-1",
                "threadId": "thread-1",
                "payload": {"headers": [{"name": "Subject", "value": "Hi"}]},
            },
        }

    monkeypatch.setattr(server, "_google_api", google_api)
    result = server._tool_call(
        _state(), tool_name="gmail_get_draft", arguments={"draft_id": "draft-1"}
    )
    assert cast(dict[str, object], result["item"])["resource_id"] == "draft-1"


# --------------------------------------------------------------------------
# ClaimContextV2 rejection: every case must dispatch zero Google API calls.
# --------------------------------------------------------------------------


def test_missing_claim_context_is_rejected(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    state = _state()
    payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body"}

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        server._tool_call(state, tool_name="gmail_create_draft", arguments={"payload": payload})

    assert exc_info.value.safe_code == "CLAIM_MISSING"
    assert exc_info.value.dispatch_started is False


def test_malformed_claim_context_missing_field_is_rejected(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    state = _state()
    payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body"}
    claim = _build_claim(
        state=state, tool_name="gmail_create_draft", execution_arguments={"payload": payload}
    )
    del claim["nonce"]

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        server._tool_call(
            state,
            tool_name="gmail_create_draft",
            arguments={"payload": payload, "claim_context": claim},
        )

    assert exc_info.value.safe_code == "CLAIM_MISSING"
    assert exc_info.value.dispatch_started is False


def test_invalid_signature_is_rejected(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    state = _state()
    payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body"}
    claim = _build_claim(
        state=state, tool_name="gmail_create_draft", execution_arguments={"payload": payload}
    )
    claim["nonce"] = "tampered-nonce"  # signature no longer matches the payload

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        server._tool_call(
            state,
            tool_name="gmail_create_draft",
            arguments={"payload": payload, "claim_context": claim},
        )

    assert exc_info.value.safe_code == "CLAIM_INVALID_SIGNATURE"
    assert exc_info.value.dispatch_started is False


def test_expired_claim_is_rejected(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    state = _state()
    payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body"}
    claim = _build_claim(
        state=state,
        tool_name="gmail_create_draft",
        execution_arguments={"payload": payload},
        issued_offset_ms=-60_000,
        ttl_ms=30_000,
    )

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        server._tool_call(
            state,
            tool_name="gmail_create_draft",
            arguments={"payload": payload, "claim_context": claim},
        )

    assert exc_info.value.safe_code == "CLAIM_EXPIRED"
    assert exc_info.value.dispatch_started is False


def test_ttl_exceeding_maximum_is_rejected(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    state = _state()
    payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body"}
    claim = _build_claim(
        state=state,
        tool_name="gmail_create_draft",
        execution_arguments={"payload": payload},
        ttl_ms=120_000,
    )

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        server._tool_call(
            state,
            tool_name="gmail_create_draft",
            arguments={"payload": payload, "claim_context": claim},
        )

    assert exc_info.value.safe_code == "CLAIM_TTL_EXCEEDED"
    assert exc_info.value.dispatch_started is False


def test_wrong_service_instance_is_rejected(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    state = _state()
    payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body"}
    claim = _build_claim(
        state=state,
        tool_name="gmail_create_draft",
        execution_arguments={"payload": payload},
        service_instance_id="svc-other",
    )

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        server._tool_call(
            state,
            tool_name="gmail_create_draft",
            arguments={"payload": payload, "claim_context": claim},
        )

    assert exc_info.value.safe_code == "CLAIM_SERVICE_INSTANCE_MISMATCH"
    assert exc_info.value.dispatch_started is False


def test_wrong_mcp_process_instance_is_rejected(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    state = _state()
    payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body"}
    claim = _build_claim(
        state=state,
        tool_name="gmail_create_draft",
        execution_arguments={"payload": payload},
        mcp_process_instance_id="mcp-other",
    )

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        server._tool_call(
            state,
            tool_name="gmail_create_draft",
            arguments={"payload": payload, "claim_context": claim},
        )

    assert exc_info.value.safe_code == "CLAIM_PROCESS_INSTANCE_MISMATCH"
    assert exc_info.value.dispatch_started is False


def test_wrong_tool_binding_is_rejected(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    state = _state()
    payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body"}
    claim = _build_claim(
        state=state, tool_name="gmail_update_draft", execution_arguments={"payload": payload}
    )

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        server._tool_call(
            state,
            tool_name="gmail_create_draft",
            arguments={"payload": payload, "claim_context": claim},
        )

    assert exc_info.value.safe_code == "CLAIM_TOOL_MISMATCH"
    assert exc_info.value.dispatch_started is False


def test_wrong_execution_arguments_hash_is_rejected(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    state = _state()
    payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body"}
    claim = _build_claim(
        state=state, tool_name="gmail_create_draft", execution_arguments={"payload": payload}
    )
    # Tamper the payload actually sent without re-issuing a matching claim.
    tampered_payload = dict(payload)
    tampered_payload["body"] = "A different body approved elsewhere"

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        server._tool_call(
            state,
            tool_name="gmail_create_draft",
            arguments={"payload": tampered_payload, "claim_context": claim},
        )

    assert exc_info.value.safe_code == "CLAIM_ARGUMENTS_MISMATCH"
    assert exc_info.value.dispatch_started is False


def test_nonce_reuse_is_rejected_and_google_is_called_at_most_once(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def google_api_call(
        _state: server._WorkspaceState,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append(method)
        return {"id": "draft-1", "message": {"id": "msg-1", "threadId": "thread-1"}}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body"}
    claim = _build_claim(
        state=state, tool_name="gmail_create_draft", execution_arguments={"payload": payload}
    )

    first = server._tool_call(
        state,
        tool_name="gmail_create_draft",
        arguments={"payload": payload, "claim_context": claim},
    )
    assert cast(dict[str, object], first["item"])["resource_id"] == "draft-1"
    assert len(calls) == 1

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        server._tool_call(
            state,
            tool_name="gmail_create_draft",
            arguments={"payload": payload, "claim_context": claim},
        )

    assert exc_info.value.safe_code == "CLAIM_TOKEN_REUSED"
    assert exc_info.value.dispatch_started is False
    assert len(calls) == 1


def test_tool_not_available_without_claim_infrastructure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    state = server._WorkspaceState(keyring=_MemorySecretStore())
    state.oauth_settings = GoogleOAuthSettings(
        google_oauth_client_id="desktop-client",
        google_oauth_client_secret="compatibility-client-secret",
    )
    # session_key/process binding never established (no handshake performed).
    payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body"}

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        server._tool_call(
            state,
            tool_name="gmail_create_draft",
            arguments={
                "payload": payload,
                "claim_context": {
                    "claim_version": 2,
                    "action_id": "a",
                    "approval_id": "b",
                    "execution_attempt_id": "c",
                    "tool_name": "gmail_create_draft",
                    "approval_arguments_hash": "x",
                    "execution_arguments_hash": "x",
                    "service_instance_id": "svc",
                    "mcp_process_instance_id": "mcp",
                    "issued_at_ms": 0,
                    "expires_at_ms": 1,
                    "nonce": "n",
                    "signature": "s",
                },
            },
        )

    assert exc_info.value.safe_code == "CLAIM_SERVICE_UNAVAILABLE"
    assert exc_info.value.dispatch_started is False


# --------------------------------------------------------------------------
# Tasks write tools (WP1)
# --------------------------------------------------------------------------


def test_tasks_create_task_dispatches_with_valid_claim(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def google_api_call(
        _state: server._WorkspaceState,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append((method, url, body))
        return {"id": "task-1", "title": "Follow up", "status": "needsAction"}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    payload: dict[str, object] = {"title": "Follow up", "notes": "Call customer"}
    claim = _build_claim(
        state=state,
        tool_name="tasks_create_task",
        execution_arguments={"task_list_id": "list-1", "payload": payload},
    )

    result = server._tool_call(
        state,
        tool_name="tasks_create_task",
        arguments={"task_list_id": "list-1", "payload": payload, "claim_context": claim},
    )

    item = cast(dict[str, object], result["item"])
    assert item["resource_id"] == "task-1"
    assert item["parent_id"] == "list-1"
    assert len(calls) == 1
    assert calls[0][0] == "POST"
    assert calls[0][1] == "https://tasks.googleapis.com/tasks/v1/lists/list-1/tasks"
    assert calls[0][2] == {"title": "Follow up", "notes": "Call customer"}


def test_tasks_update_task_supports_completion(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[str, dict[str, object] | None]] = []

    def google_api_call(
        _state: server._WorkspaceState,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append((method, body))
        return {"id": "task-1", "title": "Follow up", "status": "completed"}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    payload: dict[str, object] = {"status": "completed"}
    claim = _build_claim(
        state=state,
        tool_name="tasks_update_task",
        execution_arguments={"task_list_id": "list-1", "task_id": "task-1", "payload": payload},
    )

    result = server._tool_call(
        state,
        tool_name="tasks_update_task",
        arguments={
            "task_list_id": "list-1",
            "task_id": "task-1",
            "payload": payload,
            "claim_context": claim,
        },
    )

    item = cast(dict[str, object], result["item"])
    assert item["payload"] == {"title": "Follow up", "status": "completed"}
    assert calls == [("PATCH", {"status": "completed"})]


def test_tasks_create_task_claim_rejection_dispatches_zero_calls(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    state = _state()
    payload: dict[str, object] = {"title": "Follow up"}
    claim = _build_claim(
        state=state,
        tool_name="tasks_create_task",
        execution_arguments={"task_list_id": "list-1", "payload": payload},
    )
    tampered_payload = dict(payload)
    tampered_payload["title"] = "A different title"

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        server._tool_call(
            state,
            tool_name="tasks_create_task",
            arguments={
                "task_list_id": "list-1",
                "payload": tampered_payload,
                "claim_context": claim,
            },
        )

    assert exc_info.value.safe_code == "CLAIM_ARGUMENTS_MISMATCH"
    assert exc_info.value.dispatch_started is False


def test_tasks_update_task_missing_claim_dispatches_zero_calls(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    state = _state()

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        server._tool_call(
            state,
            tool_name="tasks_update_task",
            arguments={
                "task_list_id": "list-1",
                "task_id": "task-1",
                "payload": {"status": "completed"},
            },
        )

    assert exc_info.value.safe_code == "CLAIM_MISSING"
    assert exc_info.value.dispatch_started is False


# --------------------------------------------------------------------------
# Calendar write tools (WP2)
# --------------------------------------------------------------------------


def test_calendar_create_event_dispatches_with_valid_claim(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def google_api_call(
        _state: server._WorkspaceState,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append((method, url, body))
        return {
            "id": "event-1",
            "summary": "Review",
            "status": "confirmed",
            "start": {"dateTime": "2026-08-10T09:00:00+09:00"},
            "end": {"dateTime": "2026-08-10T10:00:00+09:00"},
        }

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    payload: dict[str, object] = {
        "title": "Review",
        "start": "2026-08-10T09:00:00+09:00",
        "end": "2026-08-10T10:00:00+09:00",
        "attendees": ["a@example.com", "b@example.com"],
    }
    claim = _build_claim(
        state=state,
        tool_name="calendar_create_event",
        execution_arguments={"calendar_id": "primary", "payload": payload},
    )

    result = server._tool_call(
        state,
        tool_name="calendar_create_event",
        arguments={"calendar_id": "primary", "payload": payload, "claim_context": claim},
    )

    item = cast(dict[str, object], result["item"])
    assert item["resource_id"] == "event-1"
    assert item["parent_id"] == "primary"
    assert len(calls) == 1
    assert calls[0][0] == "POST"
    body = cast(dict[str, object], calls[0][2])
    assert body["summary"] == "Review"
    assert body["attendees"] == [{"email": "a@example.com"}, {"email": "b@example.com"}]


def test_calendar_update_event_supports_attendee_change(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[dict[str, object] | None] = []

    def google_api_call(
        _state: server._WorkspaceState,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        assert method == "PATCH"
        calls.append(body)
        return {"id": "event-1", "summary": "Review", "status": "confirmed"}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    payload: dict[str, object] = {"attendees": ["c@example.com"]}
    claim = _build_claim(
        state=state,
        tool_name="calendar_update_event",
        execution_arguments={"calendar_id": "primary", "event_id": "event-1", "payload": payload},
    )

    result = server._tool_call(
        state,
        tool_name="calendar_update_event",
        arguments={
            "calendar_id": "primary",
            "event_id": "event-1",
            "payload": payload,
            "claim_context": claim,
        },
    )

    assert cast(dict[str, object], result["item"])["resource_id"] == "event-1"
    assert calls == [{"attendees": [{"email": "c@example.com"}]}]


def test_calendar_delete_event_dispatches_with_valid_claim(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def google_api_call(
        _state: server._WorkspaceState,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append(method)
        assert body is None
        return {}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    claim = _build_claim(
        state=state,
        tool_name="calendar_delete_event",
        execution_arguments={"calendar_id": "primary", "event_id": "event-1"},
    )

    result = server._tool_call(
        state,
        tool_name="calendar_delete_event",
        arguments={"calendar_id": "primary", "event_id": "event-1", "claim_context": claim},
    )

    item = cast(dict[str, object], result["item"])
    assert item["resource_id"] == "event-1"
    assert item["payload"] == {"status": "cancelled"}
    assert calls == ["DELETE"]


def test_calendar_create_event_claim_rejection_dispatches_zero_calls(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    state = _state()
    payload: dict[str, object] = {
        "title": "Review",
        "start": "2026-08-10T09:00:00+09:00",
        "end": "2026-08-10T10:00:00+09:00",
    }
    claim = _build_claim(
        state=state,
        tool_name="calendar_update_event",  # wrong tool binding on purpose
        execution_arguments={"calendar_id": "primary", "payload": payload},
    )

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        server._tool_call(
            state,
            tool_name="calendar_create_event",
            arguments={"calendar_id": "primary", "payload": payload, "claim_context": claim},
        )

    assert exc_info.value.safe_code == "CLAIM_TOOL_MISMATCH"
    assert exc_info.value.dispatch_started is False


def test_calendar_delete_event_nonce_reuse_dispatches_at_most_once(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def google_api_call(
        _state: server._WorkspaceState,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append(method)
        return {}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    claim = _build_claim(
        state=state,
        tool_name="calendar_delete_event",
        execution_arguments={"calendar_id": "primary", "event_id": "event-1"},
    )

    first = server._tool_call(
        state,
        tool_name="calendar_delete_event",
        arguments={"calendar_id": "primary", "event_id": "event-1", "claim_context": claim},
    )
    assert cast(dict[str, object], first["item"])["resource_id"] == "event-1"
    assert len(calls) == 1

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        server._tool_call(
            state,
            tool_name="calendar_delete_event",
            arguments={"calendar_id": "primary", "event_id": "event-1", "claim_context": claim},
        )

    assert exc_info.value.safe_code == "CLAIM_TOKEN_REUSED"
    assert len(calls) == 1
