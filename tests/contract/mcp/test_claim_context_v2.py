"""End-to-end R8.4 ClaimContextV2 contract test against the real MCP server.

Unlike test_subprocess_transport.py (which drives the read-only fake server),
this spins up the actual google_work_agent.mcp.server module as a child
process and drives it through the real SubprocessMCPTransport / gateway
signing path. No live Google credentials are configured, which lets each
test distinguish two outcomes by error code alone:

- a claim that is rejected before any Google call is made surfaces a
  CLAIM_* safe code with NOT_SENT delivery certainty;
- a claim that passes validation and reaches the real dispatch path fails
  with AUTH_EXPIRED (mapped from OAUTH_NOT_CONNECTED) because no OAuth
  credential exists in the test keyring -- proving the request reached the
  Google-dispatch gate rather than being rejected earlier.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from google_work_agent.adapters.mcp import (
    MCPArtifactConfig,
    MCPGoogleWorkspaceGateway,
    SubprocessMCPTransport,
    build_manifest_payload,
    calculate_file_sha256,
)
from google_work_agent.domain import calculate_canonical_json_hash
from google_work_agent.ports import (
    DeliveryCertainty,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourceType,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _start_transport(tmp_path: Path, *, service_instance_id: str) -> SubprocessMCPTransport:
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(json.dumps(build_manifest_payload(), sort_keys=True), encoding="utf-8")
    executable = Path(sys.executable).resolve()
    keyring_path = tmp_path / "keyring.json"
    return SubprocessMCPTransport(
        config=MCPArtifactConfig(
            executable_path=str(executable),
            manifest_path=str(manifest_path.resolve()),
            expected_binary_sha256=calculate_file_sha256(executable),
            expected_manifest_sha256=calculate_file_sha256(manifest_path.resolve()),
            expected_manifest_version="2026-08-07.p0",
            expected_protocol_version="2026-08-07.p0",
            expected_tool_registry_version="2026-08-06.p0",
            startup_timeout_ms=5_000,
            request_timeout_ms=5_000,
            max_restart_count=1,
            environment="DEVELOPMENT",
            service_instance_id=service_instance_id,
            working_directory=str(Path(__file__).resolve().parents[3]),
            module_name="google_work_agent.mcp.server",
            extra_environment={
                "GOOGLE_OAUTH_CLIENT_ID": "test-desktop-client-id",
                "GWA_TEST_KEYRING_PATH": str(keyring_path),
            },
        )
    )


def _claim_payload(*, service_instance_id: str, nonce: str) -> dict[str, object]:
    issued_at_ms = _now_ms()
    return {
        "action_id": "action-1",
        "approval_id": "approval-1",
        "attempt_id": "attempt-1",
        "service_instance_id": service_instance_id,
        "issued_at_ms": issued_at_ms,
        "expires_at_ms": issued_at_ms + 30_000,
        "nonce": nonce,
    }


def test_valid_claim_reaches_the_real_google_dispatch_gate(tmp_path: Path) -> None:
    transport = _start_transport(tmp_path, service_instance_id="svc-claim-valid")
    gateway = MCPGoogleWorkspaceGateway(transport=transport)
    try:
        payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body"}
        execution_arguments = {"payload": payload}
        claim_context = gateway.prepare_claim_context(
            claim_payload=_claim_payload(
                service_instance_id=transport.service_instance_id, nonce="nonce-valid-1"
            ),
            tool_name="gmail_create_draft",
            approval_arguments_hash=calculate_canonical_json_hash(execution_arguments),
            execution_arguments_hash=calculate_canonical_json_hash(execution_arguments),
        )

        with pytest.raises(GoogleWorkspaceGatewayError) as exc_info:
            gateway.create_gmail_draft(payload=payload, claim_context=claim_context)

        # No OAuth credential is configured, so a claim that passed
        # validation and actually reached the dispatch path fails here --
        # never with a CLAIM_* rejection.
        assert exc_info.value.code is GoogleWorkspaceErrorCode.AUTH_EXPIRED
    finally:
        transport.close()


def test_tampered_signature_is_rejected_with_zero_google_calls(tmp_path: Path) -> None:
    transport = _start_transport(tmp_path, service_instance_id="svc-claim-tampered")
    gateway = MCPGoogleWorkspaceGateway(transport=transport)
    try:
        payload: dict[str, object] = {"to": ["a@example.com"], "subject": "Hi", "body": "Body"}
        execution_arguments = {"payload": payload}
        claim_context = gateway.prepare_claim_context(
            claim_payload=_claim_payload(
                service_instance_id=transport.service_instance_id, nonce="nonce-tampered-1"
            ),
            tool_name="gmail_create_draft",
            approval_arguments_hash=calculate_canonical_json_hash(execution_arguments),
            execution_arguments_hash=calculate_canonical_json_hash(execution_arguments),
        )
        tampered = dict(claim_context)
        tampered["nonce"] = "a-different-nonce"  # invalidates the signature

        with pytest.raises(GoogleWorkspaceGatewayError) as exc_info:
            gateway.create_gmail_draft(payload=payload, claim_context=tampered)

        assert exc_info.value.delivery_certainty is DeliveryCertainty.NOT_SENT
        assert exc_info.value.code is GoogleWorkspaceErrorCode.PERMISSION_DENIED
    finally:
        transport.close()


def test_valid_tasks_claim_reaches_the_real_google_dispatch_gate(tmp_path: Path) -> None:
    transport = _start_transport(tmp_path, service_instance_id="svc-claim-tasks-valid")
    gateway = MCPGoogleWorkspaceGateway(transport=transport)
    try:
        payload: dict[str, object] = {"title": "Follow up"}
        execution_arguments = {"task_list_id": "list-1", "payload": payload}
        claim_context = gateway.prepare_claim_context(
            claim_payload=_claim_payload(
                service_instance_id=transport.service_instance_id, nonce="nonce-tasks-valid-1"
            ),
            tool_name="tasks_create_task",
            approval_arguments_hash=calculate_canonical_json_hash(execution_arguments),
            execution_arguments_hash=calculate_canonical_json_hash(execution_arguments),
        )

        with pytest.raises(GoogleWorkspaceGatewayError) as exc_info:
            gateway.create_task(task_list_id="list-1", payload=payload, claim_context=claim_context)

        assert exc_info.value.code is GoogleWorkspaceErrorCode.AUTH_EXPIRED
    finally:
        transport.close()


def test_tasks_claim_rejected_before_google_dispatch_on_expiry(tmp_path: Path) -> None:
    transport = _start_transport(tmp_path, service_instance_id="svc-claim-tasks-expired")
    gateway = MCPGoogleWorkspaceGateway(transport=transport)
    try:
        payload: dict[str, object] = {"title": "Follow up"}
        execution_arguments = {"task_list_id": "list-1", "payload": payload}
        claim_payload = _claim_payload(
            service_instance_id=transport.service_instance_id, nonce="nonce-tasks-expired-1"
        )
        claim_payload["issued_at_ms"] = _now_ms() - 120_000
        claim_payload["expires_at_ms"] = _now_ms() - 90_000
        claim_context = gateway.prepare_claim_context(
            claim_payload=claim_payload,
            tool_name="tasks_create_task",
            approval_arguments_hash=calculate_canonical_json_hash(execution_arguments),
            execution_arguments_hash=calculate_canonical_json_hash(execution_arguments),
        )

        with pytest.raises(GoogleWorkspaceGatewayError) as exc_info:
            gateway.create_task(task_list_id="list-1", payload=payload, claim_context=claim_context)

        assert exc_info.value.delivery_certainty is DeliveryCertainty.NOT_SENT
        assert exc_info.value.code is GoogleWorkspaceErrorCode.PERMISSION_DENIED
    finally:
        transport.close()


def test_valid_calendar_claim_reaches_the_real_google_dispatch_gate(tmp_path: Path) -> None:
    transport = _start_transport(tmp_path, service_instance_id="svc-claim-calendar-valid")
    gateway = MCPGoogleWorkspaceGateway(transport=transport)
    try:
        payload: dict[str, object] = {
            "title": "Review",
            "start": "2026-08-10T09:00:00+09:00",
            "end": "2026-08-10T10:00:00+09:00",
        }
        execution_arguments = {"calendar_id": "primary", "payload": payload}
        claim_context = gateway.prepare_claim_context(
            claim_payload=_claim_payload(
                service_instance_id=transport.service_instance_id, nonce="nonce-calendar-valid-1"
            ),
            tool_name="calendar_create_event",
            approval_arguments_hash=calculate_canonical_json_hash(execution_arguments),
            execution_arguments_hash=calculate_canonical_json_hash(execution_arguments),
        )

        with pytest.raises(GoogleWorkspaceGatewayError) as exc_info:
            gateway.create_calendar_event(
                calendar_id="primary", payload=payload, claim_context=claim_context
            )

        assert exc_info.value.code is GoogleWorkspaceErrorCode.AUTH_EXPIRED
    finally:
        transport.close()


def test_calendar_delete_claim_reused_is_rejected_with_zero_google_calls(tmp_path: Path) -> None:
    transport = _start_transport(tmp_path, service_instance_id="svc-claim-calendar-delete")
    gateway = MCPGoogleWorkspaceGateway(transport=transport)
    try:
        execution_arguments = {"calendar_id": "primary", "event_id": "event-1"}
        claim_context = gateway.prepare_claim_context(
            claim_payload=_claim_payload(
                service_instance_id=transport.service_instance_id, nonce="nonce-calendar-delete-1"
            ),
            tool_name="calendar_delete_event",
            approval_arguments_hash=calculate_canonical_json_hash(execution_arguments),
            execution_arguments_hash=calculate_canonical_json_hash(execution_arguments),
        )

        # No OAuth credential is configured, so the first attempt fails with
        # AUTH_EXPIRED after passing claim validation and consuming the nonce.
        with pytest.raises(GoogleWorkspaceGatewayError) as first_error:
            gateway.delete_calendar_event(
                calendar_id="primary", event_id="event-1", claim_context=claim_context
            )
        assert first_error.value.code is GoogleWorkspaceErrorCode.AUTH_EXPIRED

        # Replaying the same claim context must be rejected before any
        # further Google dispatch, proving the nonce cannot be reused.
        with pytest.raises(GoogleWorkspaceGatewayError) as second_error:
            gateway.delete_calendar_event(
                calendar_id="primary", event_id="event-1", claim_context=claim_context
            )
        assert second_error.value.delivery_certainty is DeliveryCertainty.NOT_SENT
        assert second_error.value.code is GoogleWorkspaceErrorCode.PERMISSION_DENIED
    finally:
        transport.close()


def test_wrong_execution_arguments_are_rejected_with_zero_google_calls(tmp_path: Path) -> None:
    transport = _start_transport(tmp_path, service_instance_id="svc-claim-mismatch")
    gateway = MCPGoogleWorkspaceGateway(transport=transport)
    try:
        approved_payload: dict[str, object] = {
            "to": ["a@example.com"],
            "subject": "Hi",
            "body": "Approved body",
        }
        execution_arguments = {"payload": approved_payload}
        claim_context = gateway.prepare_claim_context(
            claim_payload=_claim_payload(
                service_instance_id=transport.service_instance_id, nonce="nonce-mismatch-1"
            ),
            tool_name="gmail_create_draft",
            approval_arguments_hash=calculate_canonical_json_hash(execution_arguments),
            execution_arguments_hash=calculate_canonical_json_hash(execution_arguments),
        )
        tampered_payload = dict(approved_payload)
        tampered_payload["body"] = "A body nobody approved"

        with pytest.raises(GoogleWorkspaceGatewayError) as exc_info:
            gateway.create_gmail_draft(payload=tampered_payload, claim_context=claim_context)

        assert exc_info.value.delivery_certainty is DeliveryCertainty.NOT_SENT
        assert exc_info.value.code is GoogleWorkspaceErrorCode.PERMISSION_DENIED
    finally:
        transport.close()


def test_recovery_search_reaches_the_real_google_dispatch_gate(tmp_path: Path) -> None:
    """search_by_recovery_fingerprint carries no claim -- it's read-only -- so
    it should reach the same real Google-dispatch gate as any other read
    tool (proving it is no longer TOOL_NOT_AVAILABLE)."""

    transport = _start_transport(tmp_path, service_instance_id="svc-recovery-search")
    gateway = MCPGoogleWorkspaceGateway(transport=transport)
    try:
        with pytest.raises(GoogleWorkspaceGatewayError) as exc_info:
            gateway.search_by_recovery_fingerprint(
                resource_type=ResourceType.TASK, recovery_fingerprint="fp-contract-1"
            )
        assert exc_info.value.code is GoogleWorkspaceErrorCode.AUTH_EXPIRED
    finally:
        transport.close()
