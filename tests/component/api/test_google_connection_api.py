from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPRedirectHandler, build_opener

from fastapi.testclient import TestClient
from tests.support.fakes import DeterministicUUID, FakeClock

from google_work_agent.adapters.connectors import build_google_workspace_connector_descriptor
from google_work_agent.adapters.mcp import (
    MCPArtifactConfig,
    MCPGoogleOAuthCredentialProvider,
    MCPRuntimeStatusProvider,
    SubprocessMCPTransport,
    build_manifest_payload,
    calculate_file_sha256,
)
from google_work_agent.adapters.readiness.composite import (
    StaticLauncherProbeVerifier,
    StaticReadinessAggregator,
)
from google_work_agent.api import ApiContainer, create_app
from google_work_agent.api.security import (
    InMemoryBootstrapGrantStore,
    InMemoryLocalSessionManager,
    LocalApiAccessGuard,
)
from google_work_agent.application import (
    DisconnectGoogleService,
    GetGoogleConnectionService,
    StartGoogleOAuthService,
)
from google_work_agent.ports import LauncherProbeDecision, ReadinessReport, ReadinessState


class _CoordinatorStub:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


class _QueryStub:
    def __init__(self, runtime_provider: MCPRuntimeStatusProvider) -> None:
        self._runtime_provider = runtime_provider

    def get_runtime_summary(self):  # type: ignore[no-untyped-def]
        return self._runtime_provider.get_summary()


def test_google_connection_api_flow_over_local_mcp_process(tmp_path: Path) -> None:
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(json.dumps(build_manifest_payload(), sort_keys=True), encoding="utf-8")
    keyring_path = tmp_path / "test-keyring.json"
    fixture_manifest = (
        Path(__file__).resolve().parents[2] / "fixtures" / "product" / "manifest.json"
    )
    executable = Path(sys.executable).resolve()
    transport = SubprocessMCPTransport(
        descriptor=build_google_workspace_connector_descriptor(
            MCPArtifactConfig(
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
                service_instance_id="svc-google-api",
                working_directory=str(Path(__file__).resolve().parents[3]),
                extra_environment={
                    "GWA_TEST_KEYRING_PATH": str(keyring_path.resolve()),
                    "GWA_PRODUCT_FIXTURE_MANIFEST": str(fixture_manifest.resolve()),
                    "GOOGLE_OAUTH_CLIENT_ID": "test-desktop-client-id",
                    "GOOGLE_OAUTH_CLIENT_SECRET": "compatibility-client-secret",
                },
            )
        )
    )
    provider = MCPGoogleOAuthCredentialProvider(transport=transport)
    runtime_provider = MCPRuntimeStatusProvider(
        google_provider=provider,
        transport=transport,
        api_llm="NOT_CONFIGURED",
        ollama="NOT_AVAILABLE",
        deployment_profile="test",
    )
    clock = FakeClock(100)
    bootstrap_store = InMemoryBootstrapGrantStore()
    bootstrap_store.provision(
        secret="bootstrap-secret",
        service_instance_id="svc-google-api",
        now_ms=clock.now_ms(),
    )
    session_manager = InMemoryLocalSessionManager()
    container = ApiContainer(
        unit_of_work_factory=lambda: None,
        query_service=_QueryStub(runtime_provider),
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
                    "Subscription",
                    (),
                    {"poll": lambda self, timeout_seconds: None},
                )(),
                "close_subscription": lambda self, subscription: None,
                "publish": lambda self, event: None,
            },
        )(),
        readiness_aggregator=StaticReadinessAggregator(
            ReadinessReport(state=ReadinessState.READY, checks=())
        ),
        runtime_status_provider=runtime_provider,
        api_access_guard=LocalApiAccessGuard(
            expected_host="127.0.0.1:8766",
            expected_origin="http://127.0.0.1:8766",
            service_instance_id="svc-google-api",
            session_manager=session_manager,
            release_version="test",
            environment="test",
            now_ms=clock.now_ms,
        ),
        clock=clock,
        id_generator=DeterministicUUID(prefix="req"),
        release_version="test",
        environment="test",
        service_instance_id="svc-google-api",
        local_bind_host="127.0.0.1",
        local_bind_port=8766,
        bootstrap_grant_store=bootstrap_store,
        local_session_manager=session_manager,
        launcher_probe_verifier=StaticLauncherProbeVerifier(LauncherProbeDecision(allowed=True)),
        client_address_resolver=lambda _request: "127.0.0.1",
        start_google_oauth_service=StartGoogleOAuthService(provider=provider),
        get_google_connection_service=GetGoogleConnectionService(provider=provider),
        disconnect_google_service=DisconnectGoogleService(provider=provider),
    )
    headers = {
        "Origin": "http://127.0.0.1:8766",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    try:
        with TestClient(create_app(container), base_url="http://127.0.0.1:8766") as client:
            bootstrap = client.post(
                "/api/v1/session/bootstrap",
                json={
                    "bootstrap_secret": "bootstrap-secret",
                    "service_instance_id": "svc-google-api",
                    "api_contract_version": "1",
                },
                headers=headers,
            )
            assert bootstrap.status_code == 200

            before = client.get("/api/v1/google/connection", headers=headers)
            assert before.status_code == 200
            assert before.json()["connected"] is False

            started = client.post("/api/v1/google/oauth/start", headers=headers, json={})
            assert started.status_code == 200
            payload = started.json()
            assert "test-desktop-client-id" not in started.text
            state = parse_qs(urlparse(payload["authorization_url"]).query)["state"][0]

            response = build_opener(_NoRedirect()).open(
                f"{payload['authorization_url']}&state={state}"
            )
            assert response.code == 302
            assert urlparse(response.headers["Location"]).netloc == "accounts.google.com"

            connected = client.get("/api/v1/google/connection", headers=headers)
            assert connected.status_code == 200
            assert connected.json()["connected"] is False

            runtime = client.get("/api/v1/runtime", headers=headers)
            assert runtime.status_code == 200
            summary = runtime.json()["summary"]
            assert summary["google_connection"]["connected"] is False
            assert summary["mcp_runtime"]["process_status"] == "READY"

            disconnected = client.post("/api/v1/google/disconnect", headers=headers, json={})
            assert disconnected.status_code == 200
            assert disconnected.json()["disconnected"] is True
    finally:
        transport.close()


class _NoRedirect(HTTPRedirectHandler):
    def http_error_302(
        self,
        request: object,
        fp: object,
        code: int,
        message: str,
        headers: object,
    ) -> object:
        del request, fp, message
        return type("Response", (), {"code": code, "headers": headers})()
