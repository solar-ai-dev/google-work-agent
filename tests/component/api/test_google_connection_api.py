from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPRedirectHandler, build_opener

from fastapi.testclient import TestClient
from tests.support.fakes import DeterministicUUID, FakeClockPort
from tests.support.mcp_manifest import build_manifest_payload

from google_work_agent.adapters.connectors.google.workspace.composition import (
    GOOGLE_WORKSPACE_CONNECTOR_ID,
    build_google_workspace_connector_descriptor,
)
from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.connectors.runtime.mcp_oauth_credential import (
    McpOAuthCredentialAdapter,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    MCPArtifactConfig,
    StdioMCPClientAdapter,
    calculate_file_sha256,
)
from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.connected_account_store import (
    sqlite_connected_account_store_factory,
)
from google_work_agent.adapters.persistence.sqlite.unit_of_work import (
    sqlite_unit_of_work_factory,
)
from google_work_agent.adapters.readiness.composite import (
    StaticLauncherProbeVerifier,
    StaticReadinessAggregator,
)
from google_work_agent.adapters.system.filesystem_operational_command_replay import (
    FilesystemOperationalCommandReplayAdapter,
)
from google_work_agent.adapters.system.process_component_circuit_state import (
    ProcessComponentCircuitStateAdapter,
)
from google_work_agent.adapters.system.process_runtime_mode import ProcessRuntimeModeAdapter
from google_work_agent.api.app import create_app
from google_work_agent.api.container import ApiContainer
from google_work_agent.api.security.access_guard import LocalApiAccessGuard
from google_work_agent.api.security.bootstrap import InMemoryBootstrapGrantStore
from google_work_agent.api.security.sessions import InMemoryLocalSessionManager
from google_work_agent.application.tool_registry import load_signed_tool_registry
from google_work_agent.application.use_cases.connection.get_connection_status import (
    GetConnectionStatusHandler,
)
from google_work_agent.application.use_cases.connection.revoke_connection import (
    RevokeConnectionHandler,
)
from google_work_agent.application.use_cases.connection.start_authorization import (
    StartAuthorizationHandler,
)
from google_work_agent.application.use_cases.runtime_status.get_runtime_status import (
    GetRuntimeStatusHandler,
)
from google_work_agent.ports.llm.llm_runtime_status_port import LlmRuntimeStatusV1
from google_work_agent.ports.system.launcher_probe_port import LauncherProbeDecision
from google_work_agent.ports.system.readiness_port import (
    ReadinessReport,
    ReadinessState,
)


class _CoordinatorStub:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


class _LlmStatusStub:
    def get_status(self, provider: str) -> LlmRuntimeStatusV1:
        return LlmRuntimeStatusV1(1, provider, False, "DISABLED", None, None)


def test_google_connection_api_flow_over_local_mcp_process(tmp_path: Path) -> None:
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(json.dumps(build_manifest_payload(), sort_keys=True), encoding="utf-8")
    fixture_manifest = (
        Path(__file__).resolve().parents[2] / "fixtures" / "product" / "manifest.json"
    )
    executable = Path(sys.executable).resolve()
    registry = load_signed_tool_registry()
    runtime_registry = ConnectorRuntimeRegistry()
    transport = StdioMCPClientAdapter(
        descriptor=build_google_workspace_connector_descriptor(
            MCPArtifactConfig(
                executable_path=str(executable),
                manifest_path=str(manifest_path.resolve()),
                expected_binary_sha256=calculate_file_sha256(executable),
                expected_manifest_sha256=calculate_file_sha256(manifest_path.resolve()),
                expected_manifest_version="2026-08-07.p0",
                expected_protocol_version="2026-08-07.p0",
                expected_registry_manifest_hash=registry.entries_hash,
                startup_timeout_ms=5_000,
                request_timeout_ms=5_000,
                max_restart_count=1,
                environment="DEVELOPMENT",
                service_instance_id="svc-google-api",
                module_name="tests.fakes.google_workspace_mcp_server",
                working_directory=str(Path(__file__).resolve().parents[3]),
                extra_environment={
                    "GWA_PRODUCT_FIXTURE_MANIFEST": str(fixture_manifest.resolve()),
                    "GOOGLE_OAUTH_CLIENT_ID": "test-desktop-client-id",
                    "GOOGLE_OAUTH_CLIENT_SECRET": "compatibility-client-secret",
                },
            ),
            expected_tool_descriptors=tuple(
                registry.descriptor_expectations(GOOGLE_WORKSPACE_CONNECTOR_ID)
            ),
        ),
        runtime_registry=runtime_registry,
    )
    provider = McpOAuthCredentialAdapter(
        runtime_registry=runtime_registry,
        mcp_client=transport,
    )
    operational_replay = FilesystemOperationalCommandReplayAdapter(tmp_path / "operational-replay")
    clock = FakeClockPort(100)
    bootstrap_store = InMemoryBootstrapGrantStore()
    bootstrap_store.provision(
        secret="bootstrap-secret",
        service_instance_id="svc-google-api",
        now_ms=clock.now_ms(),
    )
    session_manager = InMemoryLocalSessionManager()
    database_path = tmp_path / "google-connection-api.db"
    connection = connect_sqlite(database_path)
    apply_migrations(connection, now_ms=clock.now_ms)
    connection.execute(
        "INSERT INTO google_accounts VALUES ('current', 'u@example.com', NULL, 1, NULL);"
    )
    connection.commit()
    connection.close()
    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    connected_account_store_factory = sqlite_connected_account_store_factory(database_path)
    container = ApiContainer(
        unit_of_work_factory=unit_of_work_factory,
        create_conversation_handler=lambda command: command,
        start_run_service=lambda command: command,
        approve_action_service=lambda command: command,
        modify_action_service=lambda command: command,
        reject_action_service=lambda command: command,
        prepare_retry_service=lambda command: command,
        cancel_run_service=lambda command: command,
        resume_run_service=lambda command: command,
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
        start_authorization_handler=StartAuthorizationHandler(
            credentials=provider,
            replay=operational_replay,
        ),
        get_connection_status_handler=GetConnectionStatusHandler(provider),
        revoke_connection_handler=RevokeConnectionHandler(
            credentials=provider,
            replay=operational_replay,
            connected_account_store_factory=connected_account_store_factory,
            now_ms=clock.now_ms,
        ),
        get_runtime_status_handler=GetRuntimeStatusHandler(
            runtime_mode=ProcessRuntimeModeAdapter("AUTO"),
            oauth=provider,
            llm_status=_LlmStatusStub(),
            circuits=ProcessComponentCircuitStateAdapter(),
        ),
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

            before = client.get("/api/v1/connections/google/status", headers=headers)
            assert before.status_code == 200
            assert before.json()["connected"] is False

            started = client.post("/api/v1/connections/google/start", headers=headers, json={})
            assert started.status_code == 200
            payload = started.json()
            assert "test-desktop-client-id" not in started.text
            state = parse_qs(urlparse(payload["authorization_url"]).query)["state"][0]

            response = build_opener(_NoRedirect()).open(
                f"{payload['authorization_url']}&state={state}"
            )
            assert response.code == 302
            assert urlparse(response.headers["Location"]).netloc == "accounts.google.com"

            connected = client.get("/api/v1/connections/google/status", headers=headers)
            assert connected.status_code == 200
            assert connected.json()["connected"] is False

            runtime = client.get("/api/v1/runtime", headers=headers)
            assert runtime.status_code == 200
            summary = runtime.json()
            assert summary["connectors"][0]["connection_status"] == "DISCONNECTED"
            assert summary["runtime_mode"]["requested_mode"] == "AUTO"
            assert set(summary) == {
                "schema_version",
                "service_instance_id",
                "connectors",
                "llm_providers",
                "component_circuits",
                "active_run_budget",
                "recovery_required",
                "release_version",
                "frontend_build_version",
                "api_contract_version",
                "deployment_profile",
                "runtime_mode",
                "database_status",
                "migration_status",
                "sse_status",
                "recent_sanitized_error_code",
                "launcher_status",
                "manifest_status",
                "session_status",
                "safe_mode",
                "last_backup_status",
                "last_migration_status",
            }

            disconnected = client.post(
                "/api/v1/connections/google/disconnect", headers=headers, json={}
            )
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
