from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient
from tests.support.external_llm_scope import build_external_scope_gate
from tests.support.fakes import (
    DeterministicUUID,
    FakeClockPort,
)

from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    LlmCredentialRouter,
    SessionMemorySecretStore,
)
from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter as CanonicalStructuredInferenceRuntimeRouter,
)
from google_work_agent.adapters.readiness.composite import (
    StaticLauncherProbeVerifier,
    StaticReadinessAggregator,
)
from google_work_agent.adapters.system.filesystem_operational_command_replay import (
    FilesystemOperationalCommandReplayAdapter,
)
from google_work_agent.api.app import create_app
from google_work_agent.api.container import ApiContainer
from google_work_agent.application.use_cases.llm_credential.delete_llm_credential import (
    DeleteLlmCredentialHandler,
)
from google_work_agent.application.use_cases.llm_credential.get_llm_credential_status import (
    GetLlmCredentialStatusHandler,
)
from google_work_agent.application.use_cases.llm_credential.store_llm_credential import (
    StoreLlmCredentialHandler,
)
from google_work_agent.ports.llm import (
    CredentialStorageMode,
)
from google_work_agent.ports.system.api_access_port import (
    AccessDecision,
    ApiRequestContext,
    EndpointPolicy,
)
from google_work_agent.ports.system.launcher_probe_port import LauncherProbeDecision
from google_work_agent.ports.system.readiness_port import ReadinessReport, ReadinessState
from google_work_agent.ports.system.sse_event_buffer_port import SseEventBufferPort


class _CoordinatorStub:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


def build_runtime(**kwargs: object) -> CanonicalStructuredInferenceRuntimeRouter:
    kwargs.pop("router", None)
    router_kwargs: dict[str, object] = {
        key: kwargs[key]
        for key in (
            "settings_service",
            "status_service",
            "credential_service",
            "api_provider",
            "ollama_provider_factory",
            "runtime_policy",
            "event_recorder",
            "schema_repairer",
            "hardware_probe",
            "api_provider_name",
        )
        if key in kwargs
    }
    kwargs.pop("api_provider")
    kwargs.clear()
    checkpoint, _projector = build_external_scope_gate()
    router_kwargs["checkpoint"] = checkpoint
    return CanonicalStructuredInferenceRuntimeRouter(**cast(Any, router_kwargs))


class _AllowGuard:
    def authorize(
        self,
        request_context: ApiRequestContext,
        *,
        endpoint_policy: EndpointPolicy,
    ) -> AccessDecision:
        del request_context, endpoint_policy
        return AccessDecision(allowed=True)


class _PublisherStub:
    def replay(self, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return ()

    def subscribe(self, run_id: str):  # type: ignore[no-untyped-def]
        del run_id
        raise AssertionError("not used")

    def close_subscription(self, subscription: object) -> None:
        del subscription


class _WorkflowRuntimeStub:
    def start(self, request):  # type: ignore[no-untyped-def]
        del request
        raise AssertionError("not used")

    def resume(self, request):  # type: ignore[no-untyped-def]
        del request
        raise AssertionError("not used")

    def request_cancel(self, request):  # type: ignore[no-untyped-def]
        del request
        raise AssertionError("not used")

    def recover_open_run(self, request):  # type: ignore[no-untyped-def]
        del request
        raise AssertionError("not used")

    def close(self) -> None:
        return None

    def flush_or_checkpoint(self) -> None:
        return None


def test_llm_runtime_routes_mask_secrets(tmp_path: Path) -> None:
    clock = FakeClockPort(1_000)
    keyring = SessionMemorySecretStore()
    credential_service = LlmCredentialRouter(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=keyring,
        session_store=SessionMemorySecretStore(),
    )
    operational_replay = FilesystemOperationalCommandReplayAdapter(tmp_path / "operational-replay")
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
        workflow_runtime=_WorkflowRuntimeStub(),
        event_publisher=cast(SseEventBufferPort, _PublisherStub()),
        readiness_aggregator=StaticReadinessAggregator(
            ReadinessReport(state=ReadinessState.READY, checks=())
        ),
        api_access_guard=_AllowGuard(),
        clock=clock,
        id_generator=DeterministicUUID(prefix="req"),
        release_version="0.1.0",
        environment="test",
        service_instance_id="svc-llm",
        launcher_probe_verifier=StaticLauncherProbeVerifier(LauncherProbeDecision(allowed=True)),
        get_llm_credential_status_handler=GetLlmCredentialStatusHandler(credential_service),
        store_llm_credential_handler=StoreLlmCredentialHandler(
            credentials=credential_service,
            replay=operational_replay,
        ),
        delete_llm_credential_handler=DeleteLlmCredentialHandler(
            credentials=credential_service,
            replay=operational_replay,
        ),
    )

    with TestClient(create_app(container)) as client:
        stored = client.put(
            "/api/v1/credentials/llm/generic",
            json={
                "schema_version": 1,
                "command_id": "credential-store-1",
                "api_key": "sk-test-secret",
                "storage_mode": CredentialStorageMode.KEYRING.value,
            },
        )
        assert stored.status_code == 200
        assert stored.json()["validation_status"] == "VALID"
        assert "sk-test-secret" not in stored.text

        connection = client.get("/api/v1/credentials/llm/generic")
        assert connection.status_code == 200
        assert connection.json()["storage_mode"] == "KEYRING"
        assert "sk-test-secret" not in connection.text

        deleted = client.request(
            "DELETE",
            "/api/v1/credentials/llm/generic",
            json={"schema_version": 1, "command_id": "credential-delete-1"},
        )
        assert deleted.status_code == 200
        assert deleted.json()["validation_status"] == "NOT_CONFIGURED"

        after_delete = client.get("/api/v1/credentials/llm/generic")
        assert after_delete.json()["validation_status"] == "NOT_CONFIGURED"
        assert "sk-test-secret" not in after_delete.text
