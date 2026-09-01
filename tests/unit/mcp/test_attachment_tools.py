"""Unit tests for WP4 Gmail attachment READ and Draft/SEND attachment wiring."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import cast

import pytest
from tests.support.claim_context import sign_claim_context

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as server,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    entrypoint as verified_server,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server.credential_provider import (
    GoogleOAuthSettings,
)
from google_work_agent.adapters.system.filesystem_attachment_staging import (
    FilesystemAttachmentStagingAdapter,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.ports.connector.contracts.google_workspace import DeliveryCertainty
from google_work_agent.ports.system.attachment_staging_port import (
    StagedAttachmentDescriptorV1,
)

SESSION_KEY = "33" * 32
SERVICE_INSTANCE_ID = "svc-attachment-1"


def _state() -> server.GoogleWorkspaceCredentialProvider:
    state = server.GoogleWorkspaceCredentialProvider(keyring=_MemorySecretStorePort())
    state.oauth_settings = GoogleOAuthSettings(
        google_oauth_client_id="desktop-client",
    )
    state.session_key = SESSION_KEY
    state.service_instance_id = SERVICE_INSTANCE_ID
    return state


class _MemorySecretStorePort:
    def put(self, key: str, secret_bytes: bytes) -> None:
        del key, secret_bytes

    def get(self, key: str) -> bytes | None:
        del key
        return None

    def delete(self, key: str) -> None:
        del key


def _build_claim(
    *,
    state: server.GoogleWorkspaceCredentialProvider,
    tool_name: str,
    execution_arguments: dict[str, object],
) -> dict[str, object]:
    issued_at_ms = server._now_ms()
    claim: dict[str, object] = {
        "claim_version": 2,
        "action_id": "action-1",
        "approval_id": "approval-1",
        "execution_attempt_id": "attempt-1",
        "tool_name": tool_name,
        "approval_arguments_hash": calculate_canonical_json_hash(execution_arguments),
        "execution_arguments_hash": calculate_canonical_json_hash(execution_arguments),
        "service_instance_id": state.service_instance_id,
        "mcp_process_instance_id": state.process_instance_id,
        "issued_at_ms": issued_at_ms,
        "expires_at_ms": issued_at_ms + 30_000,
        "nonce": "nonce-attachment-1",
    }
    assert state.session_key is not None
    claim["signature"] = sign_claim_context(state.session_key, claim)
    return claim


def _reject_google_calls(*_args: object, **_kwargs: object) -> dict[str, object]:
    pytest.fail("Google API must not be called")


# --------------------------------------------------------------------------
# gmail_get_attachment (READ)
# --------------------------------------------------------------------------


def test_gmail_get_attachment_returns_bytes_and_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"file content bytes"

    def google_api(
        _state: server.GoogleWorkspaceCredentialProvider,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, object]:
        assert "messages/msg-1/attachments/att-1" in url
        return {"size": len(raw), "data": server._b64url_encode(raw)}

    monkeypatch.setattr(server, "_google_api", google_api)
    result = verified_server._tool_call(
        _state(),
        tool_name="gmail_get_attachment",
        arguments={"message_id": "msg-1", "attachment_id": "att-1"},
    )

    assert result["size_bytes"] == len(raw)
    assert result["sha256"] == server.hashlib.sha256(raw).hexdigest()
    assert server._b64url_decode(cast(str, result["data_base64url"])) == raw


def test_gmail_get_attachment_rejects_oversized_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = b"x" * (server.MAX_ATTACHMENT_READ_BYTES + 1)

    def google_api(
        _state: server.GoogleWorkspaceCredentialProvider,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, object]:
        return {"size": len(oversized), "data": server._b64url_encode(oversized)}

    monkeypatch.setattr(server, "_google_api", google_api)
    with pytest.raises(server._WorkspaceToolError) as exc_info:
        verified_server._tool_call(
            _state(),
            tool_name="gmail_get_attachment",
            arguments={"message_id": "msg-1", "attachment_id": "att-1"},
        )
    assert exc_info.value.safe_code == "ATTACHMENT_TOO_LARGE"


def test_gmail_get_attachment_never_leaves_the_read_tool_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The attachment READ tool itself performs no claim/persistence/trace side
    effects -- it is a pure request/response mapping, matching the contract
    that only the calling FastAPI route (not this process) streams bytes to
    the browser and never touches SQLite or the LLM with them."""

    raw = b"pdf-bytes"
    monkeypatch.setattr(
        server,
        "_google_api",
        lambda *a, **k: {"size": len(raw), "data": server._b64url_encode(raw)},
    )
    result = verified_server._tool_call(
        _state(),
        tool_name="gmail_get_attachment",
        arguments={"message_id": "msg-1", "attachment_id": "att-1"},
    )
    assert set(result) == {"message_id", "attachment_id", "size_bytes", "sha256", "data_base64url"}


# --------------------------------------------------------------------------
# Draft CREATE/UPDATE with staged attachments
# --------------------------------------------------------------------------


@pytest.fixture
def staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FilesystemAttachmentStagingAdapter:
    staging_dir = tmp_path / "attachments"
    monkeypatch.setenv(server.ATTACHMENT_STAGING_DIR_ENV, str(staging_dir))
    return FilesystemAttachmentStagingAdapter(staging_dir=staging_dir)


def test_gmail_create_draft_embeds_a_verified_staged_attachment(
    monkeypatch: pytest.MonkeyPatch,
    staging: FilesystemAttachmentStagingAdapter,
) -> None:
    descriptor = staging.stage(
        operation_ref="stage-report",
        file_bytes=b"report bytes",
        filename="report.pdf",
        mime_type="application/pdf",
    )
    captured: dict[str, object] = {}

    def google_api_call(
        _state: server.GoogleWorkspaceCredentialProvider,
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
        "subject": "Report",
        "body": "See attached",
        "attachments": [descriptor.to_json()],
    }
    claim = _build_claim(
        state=state, tool_name="gmail_create_draft", execution_arguments={"payload": payload}
    )

    verified_server._tool_call(
        state,
        tool_name="gmail_create_draft",
        arguments={"payload": payload, "claim_context": claim},
    )

    body = cast(dict[str, object], captured["body"])
    message = cast(dict[str, object], body["message"])
    raw_bytes = server._b64url_decode(cast(str, message["raw"]))
    assert base64.b64encode(b"report bytes") in raw_bytes
    assert b"report.pdf" in raw_bytes
    assert b"application/pdf" in raw_bytes


def test_gmail_create_draft_rejects_missing_staged_attachment(
    monkeypatch: pytest.MonkeyPatch,
    staging: FilesystemAttachmentStagingAdapter,
) -> None:
    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    state = _state()
    fake_descriptor = StagedAttachmentDescriptorV1(
        schema_version=1,
        staged_attachment_id="never-staged",
        filename="a.txt",
        mime_type="text/plain",
        size_bytes=1,
        sha256="0" * 64,
        expires_at_ms=server._now_ms() + 30_000,
    )
    payload: dict[str, object] = {
        "to": ["a@example.com"],
        "subject": "Hi",
        "body": "Body",
        "attachments": [fake_descriptor.to_json()],
    }
    claim = _build_claim(
        state=state, tool_name="gmail_create_draft", execution_arguments={"payload": payload}
    )

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        verified_server._tool_call(
            state,
            tool_name="gmail_create_draft",
            arguments={"payload": payload, "claim_context": claim},
        )

    assert exc_info.value.safe_code == "ATTACHMENT_STAGING_MISSING"
    assert exc_info.value.delivery_certainty is DeliveryCertainty.NOT_SENT


def test_gmail_create_draft_rejects_hash_mismatched_staged_attachment(
    monkeypatch: pytest.MonkeyPatch,
    staging: FilesystemAttachmentStagingAdapter,
) -> None:
    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    real_descriptor = staging.stage(
        operation_ref="stage-real",
        file_bytes=b"real bytes",
        filename="a.txt",
        mime_type="text/plain",
    )
    tampered_descriptor = StagedAttachmentDescriptorV1(
        schema_version=1,
        staged_attachment_id=real_descriptor.staged_attachment_id,
        filename=real_descriptor.filename,
        mime_type=real_descriptor.mime_type,
        size_bytes=real_descriptor.size_bytes,
        sha256="f" * 64,
        expires_at_ms=real_descriptor.expires_at_ms,
    )
    state = _state()
    payload: dict[str, object] = {
        "to": ["a@example.com"],
        "subject": "Hi",
        "body": "Body",
        "attachments": [tampered_descriptor.to_json()],
    }
    claim = _build_claim(
        state=state, tool_name="gmail_create_draft", execution_arguments={"payload": payload}
    )

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        verified_server._tool_call(
            state,
            tool_name="gmail_create_draft",
            arguments={"payload": payload, "claim_context": claim},
        )

    assert exc_info.value.safe_code == "ATTACHMENT_HASH_MISMATCH"
    assert exc_info.value.delivery_certainty is DeliveryCertainty.NOT_SENT


def test_gmail_create_draft_rejects_expired_staged_attachment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clock = {"now": 1_000_000}
    staging_dir = tmp_path / "attachments"
    monkeypatch.setenv(server.ATTACHMENT_STAGING_DIR_ENV, str(staging_dir))
    expiring_staging = FilesystemAttachmentStagingAdapter(
        staging_dir=staging_dir, now_ms=lambda: clock["now"]
    )
    descriptor = expiring_staging.stage(
        operation_ref="stage-expiring",
        file_bytes=b"bytes",
        filename="a.txt",
        mime_type="text/plain",
    )
    clock["now"] += 20 * 60 * 1000  # advance past the 15 minute TTL

    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    state = _state()
    payload: dict[str, object] = {
        "to": ["a@example.com"],
        "subject": "Hi",
        "body": "Body",
        "attachments": [descriptor.to_json()],
    }
    claim = _build_claim(
        state=state, tool_name="gmail_create_draft", execution_arguments={"payload": payload}
    )

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        verified_server._tool_call(
            state,
            tool_name="gmail_create_draft",
            arguments={"payload": payload, "claim_context": claim},
        )

    assert exc_info.value.safe_code == "ATTACHMENT_STAGING_EXPIRED"
    assert exc_info.value.delivery_certainty is DeliveryCertainty.NOT_SENT


def test_gmail_create_draft_without_staging_env_rejects_attachment_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(server.ATTACHMENT_STAGING_DIR_ENV, raising=False)
    monkeypatch.setattr(server, "_google_api_call", _reject_google_calls)
    state = _state()
    payload: dict[str, object] = {
        "to": ["a@example.com"],
        "subject": "Hi",
        "body": "Body",
        "attachments": [
            {
                "staged_attachment_id": "x",
                "filename": "a.txt",
                "mime_type": "text/plain",
                "size_bytes": 1,
                "sha256": "0" * 64,
            }
        ],
    }
    claim = _build_claim(
        state=state, tool_name="gmail_create_draft", execution_arguments={"payload": payload}
    )

    with pytest.raises(server._WorkspaceToolError) as exc_info:
        verified_server._tool_call(
            state,
            tool_name="gmail_create_draft",
            arguments={"payload": payload, "claim_context": claim},
        )

    assert exc_info.value.safe_code == "ATTACHMENT_STAGING_UNAVAILABLE"
    assert exc_info.value.delivery_certainty is DeliveryCertainty.NOT_SENT


def test_gmail_create_draft_without_attachments_key_never_touches_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(server.ATTACHMENT_STAGING_DIR_ENV, raising=False)

    def google_api_call(
        _state: server.GoogleWorkspaceCredentialProvider,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {"id": "draft-1", "message": {"id": "msg-1", "threadId": "thread-1"}}

    monkeypatch.setattr(server, "_google_api_call", google_api_call)
    state = _state()
    payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body"}
    claim = _build_claim(
        state=state, tool_name="gmail_create_draft", execution_arguments={"payload": payload}
    )

    result = verified_server._tool_call(
        state,
        tool_name="gmail_create_draft",
        arguments={"payload": payload, "claim_context": claim},
    )

    assert cast(dict[str, object], result["item"])["resource_id"] == "draft-1"
