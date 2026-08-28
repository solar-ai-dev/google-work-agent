from fastapi.testclient import TestClient
from tests.support.fakes import DeterministicUUID, FakeClockPort

from google_work_agent.adapters.readiness.composite import (
    StaticLauncherProbeVerifier,
    StaticReadinessAggregator,
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
from google_work_agent.application.use_cases.runtime_status.get_runtime_status import (
    GetRuntimeStatusHandler,
)
from google_work_agent.ports.connector.oauth_credential_port import ConnectionMetadataV1
from google_work_agent.ports.llm.llm_runtime_status_port import LlmRuntimeStatusV1
from google_work_agent.ports.system.launcher_probe_port import LauncherProbeDecision
from google_work_agent.ports.system.readiness_port import (
    ReadinessCheckResult,
    ReadinessReport,
    ReadinessState,
)


class _CoordinatorStub:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


class _OAuthStatusStub:
    def get_connection_status(self, connector_id: str) -> ConnectionMetadataV1:
        return ConnectionMetadataV1(1, connector_id, None, None, "DISCONNECTED", (), ())


class _LlmStatusStub:
    def get_status(self, provider: str) -> LlmRuntimeStatusV1:
        return LlmRuntimeStatusV1(1, provider, False, "DISABLED", None, None)


def _build_client(*, with_probe: bool = True) -> TestClient:
    clock = FakeClockPort(100)
    bind_host = "127.0.0.1"
    bind_port = 8765
    session_manager = InMemoryLocalSessionManager()
    bootstrap_store = InMemoryBootstrapGrantStore()
    bootstrap_store.provision(
        secret="CANARY_BOOTSTRAP_SECRET",
        service_instance_id="svc-test",
        now_ms=clock.now_ms(),
    )
    container = ApiContainer(
        unit_of_work_factory=lambda: None,
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
            ReadinessReport(
                state=ReadinessState.READY,
                checks=(
                    ReadinessCheckResult(
                        name="sqlite_connection",
                        state=ReadinessState.READY,
                    ),
                ),
            )
        ),
        api_access_guard=LocalApiAccessGuard(
            expected_host=f"{bind_host}:{bind_port}",
            expected_origin=f"http://{bind_host}:{bind_port}",
            service_instance_id="svc-test",
            session_manager=session_manager,
            release_version="test",
            environment="test",
            now_ms=clock.now_ms,
        ),
        clock=clock,
        id_generator=DeterministicUUID(prefix="req"),
        release_version="test",
        environment="test",
        service_instance_id="svc-test",
        local_bind_host=bind_host,
        local_bind_port=bind_port,
        bootstrap_grant_store=bootstrap_store,
        local_session_manager=session_manager,
        launcher_probe_verifier=(
            StaticLauncherProbeVerifier(LauncherProbeDecision(allowed=True)) if with_probe else None
        ),
        client_address_resolver=lambda _request: "127.0.0.1",
        get_runtime_status_handler=GetRuntimeStatusHandler(
            runtime_mode=ProcessRuntimeModeAdapter("AUTO"),
            oauth=_OAuthStatusStub(),
            llm_status=_LlmStatusStub(),
            circuits=ProcessComponentCircuitStateAdapter(),
        ),
    )
    return TestClient(create_app(container), base_url=f"http://{bind_host}:{bind_port}")


def test_bootstrap_sets_cookie_and_runtime_requires_session() -> None:
    headers = {
        "Origin": "http://127.0.0.1:8765",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    with _build_client() as client:
        unauthorized = client.get("/api/v1/runtime", headers=headers)
        bootstrap = client.post(
            "/api/v1/session/bootstrap",
            json={
                "bootstrap_secret": "CANARY_BOOTSTRAP_SECRET",
                "service_instance_id": "svc-test",
                "api_contract_version": "1",
            },
            headers=headers,
        )
        authorized = client.get("/api/v1/runtime", headers=headers)

    assert unauthorized.status_code == 401
    assert bootstrap.status_code == 200
    assert bootstrap.headers["cache-control"] == "no-store"
    assert "gwa_session=" in bootstrap.headers["set-cookie"]
    assert authorized.status_code == 200


def test_bootstrap_rejection_and_unknown_api_path_do_not_echo_canaries() -> None:
    headers = {
        "Origin": "http://127.0.0.1:8765",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    with _build_client() as client:
        bootstrap = client.post(
            "/api/v1/session/bootstrap",
            json={
                "bootstrap_secret": "CANARY_BOOTSTRAP_SECRET_typo",
                "service_instance_id": "svc-test",
                "api_contract_version": "1",
            },
            headers=headers,
        )
        unknown = client.get("/api/v1/unknown", headers=headers)

    assert bootstrap.status_code == 401
    assert "CANARY_BOOTSTRAP_SECRET" not in bootstrap.text
    assert unknown.status_code == 401
    assert "CANARY_BOOTSTRAP_SECRET" not in unknown.text


def test_ready_route_fails_closed_when_launcher_probe_is_missing() -> None:
    with _build_client(with_probe=False) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "NOT_READY"
