"""Component tests for the Gmail attachment download and staging routes (WP4)."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from tests.support.fakes import DeterministicUUID, FakeClock

from google_work_agent.adapters.mcp import (
    MCPArtifactConfig,
    SubprocessMCPTransport,
    build_manifest_payload,
    calculate_file_sha256,
)
from google_work_agent.adapters.mcp.gateway import MCPGmailAttachmentGateway
from google_work_agent.adapters.readiness.composite import (
    StaticLauncherProbeVerifier,
    StaticReadinessAggregator,
)
from google_work_agent.adapters.runtime.attachment_staging import LocalAttachmentStaging
from google_work_agent.api import ApiContainer, create_app
from google_work_agent.api.security import (
    InMemoryBootstrapGrantStore,
    InMemoryLocalSessionManager,
    LocalApiAccessGuard,
)
from google_work_agent.application.attachments import (
    GetGmailAttachmentService,
    StageAttachmentService,
)
from google_work_agent.ports import LauncherProbeDecision, ReadinessReport, ReadinessState


class _CoordinatorStub:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


def _start_transport(tmp_path: Path, *, service_instance_id: str) -> SubprocessMCPTransport:
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(json.dumps(build_manifest_payload(), sort_keys=True), encoding="utf-8")
    executable = Path(sys.executable).resolve()
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
            extra_environment={
                "GWA_TEST_KEYRING_PATH": str((tmp_path / "keyring.json").resolve()),
                "GOOGLE_OAUTH_CLIENT_ID": "test-desktop-client-id",
                "GOOGLE_OAUTH_CLIENT_SECRET": "compatibility-client-secret",
            },
        )
    )


def _container(
    tmp_path: Path,
    *,
    service_instance_id: str,
    transport: SubprocessMCPTransport,
    staging_dir: Path,
) -> ApiContainer:
    clock = FakeClock(100)
    bootstrap_store = InMemoryBootstrapGrantStore()
    bootstrap_store.provision(
        secret="bootstrap-secret", service_instance_id=service_instance_id, now_ms=clock.now_ms()
    )
    session_manager = InMemoryLocalSessionManager()
    attachment_gateway = MCPGmailAttachmentGateway(transport=transport)
    staging = LocalAttachmentStaging(staging_dir=staging_dir)
    return ApiContainer(
        unit_of_work_factory=lambda: None,
        query_service=None,
        create_conversation_service=lambda command: command,
        start_run_service=lambda command: command,
        approve_action_service=lambda command: command,
        modify_action_service=lambda command: command,
        reject_action_service=lambda command: command,
        prepare_retry_service=lambda command: command,
        cancel_run_service=lambda command: command,
        resume_run_service=lambda command: command,
        local_run_coordinator=_CoordinatorStub(),
        workflow_runtime=type("Runtime", (), {"close": lambda self: None})(),
        event_publisher=type(
            "Publisher",
            (),
            {
                "replay": lambda self, **kwargs: (),
                "subscribe": lambda self, run_id: type(
                    "Subscription", (), {"poll": lambda self, timeout_seconds: None}
                )(),
                "close_subscription": lambda self, subscription: None,
                "publish": lambda self, event: None,
            },
        )(),
        readiness_aggregator=StaticReadinessAggregator(
            ReadinessReport(state=ReadinessState.READY, checks=())
        ),
        runtime_status_provider=type("RuntimeStatus", (), {"get_summary": lambda self: {}})(),
        api_access_guard=LocalApiAccessGuard(
            expected_host="127.0.0.1:8767",
            expected_origin="http://127.0.0.1:8767",
            service_instance_id=service_instance_id,
            session_manager=session_manager,
            release_version="test",
            environment="test",
            now_ms=clock.now_ms,
        ),
        clock=clock,
        id_generator=DeterministicUUID(prefix="req"),
        release_version="test",
        environment="test",
        service_instance_id=service_instance_id,
        local_bind_host="127.0.0.1",
        local_bind_port=8767,
        bootstrap_grant_store=bootstrap_store,
        local_session_manager=session_manager,
        launcher_probe_verifier=StaticLauncherProbeVerifier(LauncherProbeDecision(allowed=True)),
        client_address_resolver=lambda _request: "127.0.0.1",
        get_gmail_attachment_service=GetGmailAttachmentService(gateway=attachment_gateway),
        stage_attachment_service=StageAttachmentService(staging=staging),
    )


_HEADERS = {
    "Origin": "http://127.0.0.1:8767",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}


def _bootstrap(client: TestClient, *, service_instance_id: str) -> None:
    response = client.post(
        "/api/v1/session/bootstrap",
        json={
            "bootstrap_secret": "bootstrap-secret",
            "service_instance_id": service_instance_id,
            "api_contract_version": "1",
        },
        headers=_HEADERS,
    )
    assert response.status_code == 200


def test_stage_attachment_returns_descriptor_not_bytes(tmp_path: Path) -> None:
    transport = _start_transport(tmp_path, service_instance_id="svc-attachment-stage")
    container = _container(
        tmp_path,
        service_instance_id="svc-attachment-stage",
        transport=transport,
        staging_dir=tmp_path / "staging",
    )
    try:
        with TestClient(create_app(container), base_url="http://127.0.0.1:8767") as client:
            _bootstrap(client, service_instance_id="svc-attachment-stage")

            response = client.post(
                "/api/v1/attachments/stage",
                headers=_HEADERS,
                json={
                    "filename": "report.pdf",
                    "mime_type": "application/pdf",
                    "data_base64": base64.b64encode(b"pdf bytes").decode("ascii"),
                },
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["filename"] == "report.pdf"
            assert payload["mime_type"] == "application/pdf"
            assert payload["size_bytes"] == len(b"pdf bytes")
            assert len(payload["sha256"]) == 64
            assert "data" not in payload
            assert b"pdf bytes" not in response.content
    finally:
        transport.close()


def test_stage_attachment_rejects_empty_upload(tmp_path: Path) -> None:
    transport = _start_transport(tmp_path, service_instance_id="svc-attachment-empty")
    container = _container(
        tmp_path,
        service_instance_id="svc-attachment-empty",
        transport=transport,
        staging_dir=tmp_path / "staging",
    )
    try:
        with TestClient(create_app(container), base_url="http://127.0.0.1:8767") as client:
            _bootstrap(client, service_instance_id="svc-attachment-empty")

            response = client.post(
                "/api/v1/attachments/stage",
                headers=_HEADERS,
                json={"filename": "empty.txt", "mime_type": "text/plain", "data_base64": ""},
            )

            assert response.status_code == 422
            assert response.json()["detail_code"] == "ATTACHMENT_EMPTY"
    finally:
        transport.close()


def test_stage_attachment_requires_local_session(tmp_path: Path) -> None:
    transport = _start_transport(tmp_path, service_instance_id="svc-attachment-noauth")
    container = _container(
        tmp_path,
        service_instance_id="svc-attachment-noauth",
        transport=transport,
        staging_dir=tmp_path / "staging",
    )
    try:
        with TestClient(create_app(container), base_url="http://127.0.0.1:8767") as client:
            response = client.post(
                "/api/v1/attachments/stage",
                headers=_HEADERS,
                json={
                    "filename": "a.txt",
                    "mime_type": "text/plain",
                    "data_base64": base64.b64encode(b"data").decode("ascii"),
                },
            )
            assert response.status_code in (401, 403)
    finally:
        transport.close()


def test_download_attachment_reaches_real_google_dispatch_gate(tmp_path: Path) -> None:
    """No OAuth credential is configured, so the request must fail only after
    passing local-session auth and reaching the real MCP attachment tool --
    proving the route -> service -> gateway -> MCP wiring is real, not stubbed."""

    transport = _start_transport(tmp_path, service_instance_id="svc-attachment-download")
    container = _container(
        tmp_path,
        service_instance_id="svc-attachment-download",
        transport=transport,
        staging_dir=tmp_path / "staging",
    )
    try:
        with TestClient(create_app(container), base_url="http://127.0.0.1:8767") as client:
            _bootstrap(client, service_instance_id="svc-attachment-download")

            response = client.get(
                "/api/v1/gmail/messages/msg-1/attachments/att-1", headers=_HEADERS
            )

            assert response.status_code == 401
            assert response.json()["detail_code"] == "GOOGLE_AUTH_EXPIRED"
    finally:
        transport.close()
