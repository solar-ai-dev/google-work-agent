from __future__ import annotations

from typing import cast

import pytest

from google_work_agent.adapters.mcp.gateway import MCPGoogleWorkspaceGateway
from google_work_agent.application.write_approval_contracts import DEFAULT_APPROVAL_TTL_MS
from google_work_agent.application.write_claim import ClaimWriteActionService
from google_work_agent.application.write_execution_integrity import (
    CLAIM_TOKEN_VERSION,
    issue_claim_token,
    read_claim_token,
)
from google_work_agent.domain import calculate_canonical_json_hash
from google_work_agent.domain.claim_contract import (
    CLAIM_CONTEXT_DEFAULT_TTL_MS,
    CLAIM_CONTEXT_MAX_TTL_MS,
)
from google_work_agent.adapters.connectors.google.mcp import workspace_tools as server
from google_work_agent.ports import MCPClientPort

_SESSION_KEY = "11" * 32
_SIGNING_SECRET = "application-signing-secret"
_SERVICE_INSTANCE_ID = "svc-test-1"


class _ClaimSigningTransport:
    def __init__(self, *, process_instance_id: str) -> None:
        self.process_instance_id = process_instance_id

    def sign_claim_context(self, payload: dict[str, object]) -> str:
        return server._sign_claim_context(_SESSION_KEY, payload)


def _claim_service(*, ttl_ms: int | None = None) -> ClaimWriteActionService:
    kwargs: dict[str, object] = {
        "unit_of_work_factory": lambda: None,
        "now_ms": lambda: 1_000,
        "signing_secret": _SIGNING_SECRET,
        "service_instance_id": _SERVICE_INSTANCE_ID,
    }
    if ttl_ms is not None:
        kwargs["claim_ttl_ms"] = ttl_ms
    return ClaimWriteActionService(**kwargs)  # type: ignore[arg-type]


def test_application_default_claim_ttl_is_canonical_30_seconds() -> None:
    service = _claim_service()

    assert service._claim_ttl_ms == CLAIM_CONTEXT_DEFAULT_TTL_MS == 30_000
    assert server.CLAIM_CONTEXT_MAX_TTL_MS == CLAIM_CONTEXT_MAX_TTL_MS


def test_application_claim_over_60_seconds_fails_closed_before_issue() -> None:
    with pytest.raises(ValueError, match="CLAIM_CONTEXT_MAX_TTL_MS"):
        _claim_service(ttl_ms=CLAIM_CONTEXT_MAX_TTL_MS + 1)


def test_approval_ttl_is_separate_and_does_not_expand_claim_ttl() -> None:
    assert DEFAULT_APPROVAL_TTL_MS == 30 * 60 * 1000
    assert _claim_service()._claim_ttl_ms == 30_000
    assert DEFAULT_APPROVAL_TTL_MS != CLAIM_CONTEXT_DEFAULT_TTL_MS


def test_application_issued_claim_converts_to_mcp_claim_and_dispatches(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state = server._WorkspaceState(keyring=_MemorySecretStorePort())
    state.session_key = _SESSION_KEY
    state.service_instance_id = _SERVICE_INSTANCE_ID
    business_payload: dict[str, object] = {
        "to": ["a@example.com"],
        "subject": "Hi",
        "body": "Body",
    }
    execution_arguments = {"payload": business_payload}
    arguments_hash = calculate_canonical_json_hash(execution_arguments)
    now_ms = server._now_ms()
    token = issue_claim_token(
        {
            "version": CLAIM_TOKEN_VERSION,
            "action_id": "action-1",
            "approval_id": "approval-1",
            "attempt_id": "attempt-1",
            "tool_name": "gmail_create_draft",
            "arguments_hash": arguments_hash,
            "service_instance_id": _SERVICE_INSTANCE_ID,
            "nonce": "nonce-1",
            "issued_at_ms": now_ms,
            "expires_at_ms": now_ms + CLAIM_CONTEXT_DEFAULT_TTL_MS,
        },
        signing_secret=_SIGNING_SECRET,
    )
    application_claim = read_claim_token(token, signing_secret=_SIGNING_SECRET)
    transport = _ClaimSigningTransport(process_instance_id=state.process_instance_id)
    gateway = MCPGoogleWorkspaceGateway(transport=cast(MCPClientPort, transport))
    claim_context = gateway.prepare_claim_context(
        claim_payload=application_claim,
        tool_name="gmail_create_draft",
        approval_arguments_hash=arguments_hash,
        execution_arguments_hash=arguments_hash,
    )
    provider_calls = 0

    def google_api_call(
        _state: object,
        _method: str,
        _url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        nonlocal provider_calls
        del params, body
        provider_calls += 1
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

    result = server._tool_call(
        state,
        tool_name="gmail_create_draft",
        arguments={"payload": business_payload, "claim_context": claim_context},
    )

    assert cast(dict[str, object], result["item"])["resource_id"] == "draft-1"
    assert provider_calls == 1


class _MemorySecretStorePort:
    def set_secret(self, *, service: str, account: str, secret: str) -> None:
        del service, account, secret

    def get_secret(self, *, service: str, account: str) -> str | None:
        del service, account
        return None

    def delete_secret(self, *, service: str, account: str) -> bool:
        del service, account
        return True
