from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient
from tests.support.fakes import (
    DeterministicUUID,
    FakeAPIProviderTransport,
    FakeClockPort,
    FakeHardwareProbe,
    FakeOllamaTransport,
    approved_model,
)

from google_work_agent.adapters.llm.gemini.structured_inference import GeminiConnectionService
from google_work_agent.adapters.llm.gemini.structured_inference import (
    GeminiStructuredInferenceAdapter as StructuredInferenceRuntimeRouter,
)
from google_work_agent.adapters.llm.ollama.structured_inference import (
    OllamaStructuredInferenceAdapter,
)
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    LlmCredentialRouter,
    SessionMemorySecretStore,
)
from google_work_agent.adapters.llm.runtime.llm_runtime_status_router import LlmRuntimeStatusRouter
from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter as CanonicalStructuredInferenceRuntimeRouter,
)
from google_work_agent.adapters.readiness.composite import (
    StaticLauncherProbeVerifier,
    StaticReadinessAggregator,
)
from google_work_agent.adapters.runtime import BuildProfile
from google_work_agent.adapters.system.filesystem_operational_command_replay import (
    FilesystemOperationalCommandReplayAdapter,
)
from google_work_agent.api.app import create_app
from google_work_agent.api.container import ApiContainer
from google_work_agent.application.llm import (
    LLMRuntimeService as _LLMRuntimeService,
)
from google_work_agent.application.llm import (
    TestLLMConnectionService as LLMConnectionTestService,
)
from google_work_agent.application.use_cases.llm_credential.delete_llm_credential import (
    DeleteLlmCredentialHandler,
)
from google_work_agent.application.use_cases.llm_credential.get_llm_credential_status import (
    GetLlmCredentialStatusHandler,
)
from google_work_agent.application.use_cases.llm_credential.store_llm_credential import (
    StoreLlmCredentialHandler,
)
from google_work_agent.ports import (
    AccessDecision,
    AppSettings,
    ApiRequestContext,
    CredentialStorageMode,
    EndpointPolicy,
    LauncherProbeDecision,
    ProviderResponsePayload,
    ReadinessReport,
    ReadinessState,
    RuntimePolicy,
    RuntimeStatusProvider,
    RuntimeSummary,
    SseEventBufferPort,
    WorkflowRuntime,
)


class _CoordinatorStub:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


def LLMRuntimeService(**kwargs: object) -> _LLMRuntimeService:  # noqa: N802
    kwargs.pop("router", None)
    router_kwargs = {
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
    kwargs.pop("hardware_probe", None)
    kwargs.pop("api_provider_name", None)
    return _LLMRuntimeService(
        structured_inference=CanonicalStructuredInferenceRuntimeRouter(**router_kwargs),
        **kwargs,
    )


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


class _RuntimeStatusProvider(RuntimeStatusProvider):
    def get_summary(self) -> RuntimeSummary:
        return RuntimeSummary(
            google="CONNECTED",
            mcp="READY",
            api_llm="NOT_CONFIGURED",
            ollama="NOT_AVAILABLE",
            deployment_profile="test",
            recovery_required_run_ids=(),
            open_run_ids=(),
            llm={},
        )


class _QueryStub:
    def __init__(self, runtime_status_provider: RuntimeStatusProvider) -> None:
        self._runtime_status_provider = runtime_status_provider

    def get_runtime_summary(self) -> RuntimeSummary:
        return self._runtime_status_provider.get_summary()


def test_llm_runtime_routes_mask_secrets_and_project_runtime_state(tmp_path: Path) -> None:
    clock = FakeClockPort(1_000)
    keyring = SessionMemorySecretStore()
    api_transport = FakeAPIProviderTransport()
    api_transport.queued_payloads.append(
        ProviderResponsePayload(
            content={"answer": "ok"},
            model="api-model",
            provider_request_id="provider-1",
            input_tokens=10,
            output_tokens=4,
            latency_ms=25,
        )
    )
    ollama_transport = FakeOllamaTransport()
    credential_service = LlmCredentialRouter(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=keyring,
        session_store=SessionMemorySecretStore(),
    )
    runtime_settings = lambda: AppSettings(
        deployment_profile=BuildProfile.LOCAL_CAPABLE.value,
        requested_runtime_mode="API_LLM",
        external_llm_consent=True,
        ollama_endpoint="http://127.0.0.1:11434",
        approved_model_id=approved_model().model_id,
    )
    status_service = LlmRuntimeStatusRouter(
        build_profile=BuildProfile.LOCAL_CAPABLE.value,
        settings_service=runtime_settings,
        credential_service=credential_service,
        api_connection_service=GeminiConnectionService(api_transport),
        ollama_probe=type(
            "_Probe",
            (),
            {
                "probe": lambda self, endpoint, approved_model: ollama_transport.probe(  # noqa: ARG005
                    endpoint=endpoint or "http://127.0.0.1:11434",
                    model_id=None if approved_model is None else approved_model.model_id,
                    timeout_seconds=5,
                )
            },
        )(),
        approved_models={approved_model().model_id: approved_model()},
        runtime_policy=RuntimePolicy(),
        api_provider_name="generic",
    )
    runtime_provider = _RuntimeStatusProvider()
    operational_replay = FilesystemOperationalCommandReplayAdapter(
        tmp_path / "operational-replay"
    )
    container = ApiContainer(
        unit_of_work_factory=lambda: None,
        query_service=_QueryStub(runtime_provider),
        create_conversation_handler=lambda command: command,
        start_run_service=lambda command: command,
        approve_action_service=lambda command: command,
        modify_action_service=lambda command: command,
        reject_action_service=lambda command: command,
        prepare_retry_service=lambda command: command,
        cancel_run_service=lambda command: command,
        resume_run_service=lambda command: command,
        workflow_runtime=cast(WorkflowRuntime, _WorkflowRuntimeStub()),
        event_publisher=cast(SseEventBufferPort, _PublisherStub()),
        readiness_aggregator=StaticReadinessAggregator(
            ReadinessReport(state=ReadinessState.READY, checks=())
        ),
        runtime_status_provider=runtime_provider,
        api_access_guard=_AllowGuard(),
        clock=clock,
        id_generator=DeterministicUUID(prefix="req"),
        release_version="0.1.0",
        environment="test",
        service_instance_id="svc-llm",
        launcher_probe_verifier=StaticLauncherProbeVerifier(LauncherProbeDecision(allowed=True)),
        get_llm_credential_status_handler=GetLlmCredentialStatusHandler(
            credential_service
        ),
        store_llm_credential_handler=StoreLlmCredentialHandler(
            credentials=credential_service,
            replay=operational_replay,
        ),
        delete_llm_credential_handler=DeleteLlmCredentialHandler(
            credentials=credential_service,
            replay=operational_replay,
        ),
        test_llm_connection_service=None,
    )

    with TestClient(create_app(container)) as client:
        stored = client.put(
            "/api/v1/credentials/llm/generic",
            json={"api_key": "sk-test-secret", "storage_mode": CredentialStorageMode.KEYRING.value},
        )
        assert stored.status_code == 200
        assert stored.json()["credential_state"] == "VALID"
        assert "sk-test-secret" not in stored.text

        connection = client.get("/api/v1/credentials/llm/generic")
        assert connection.status_code == 200
        assert connection.json()["llm"]["storage_mode"] == "KEYRING"
        assert "sk-test-secret" not in connection.text

        deleted = client.delete("/api/v1/credentials/llm/generic")
        assert deleted.status_code == 200
        assert deleted.json()["credential_state"] == "NOT_CONFIGURED"

        after_delete = client.get("/api/v1/credentials/llm/generic")
        assert after_delete.json()["llm"]["validation_status"] == "NOT_CONFIGURED"
        assert "sk-test-secret" not in after_delete.text
