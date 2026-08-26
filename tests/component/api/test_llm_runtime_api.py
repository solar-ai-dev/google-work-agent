from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient
from tests.support.fakes import (
    DeterministicUUID,
    FakeAPIProviderTransport,
    FakeClockPort,
    FakeHardwareProbe,
    FakeKeyring,
    FakeOllamaTransport,
    approved_model,
)

from google_work_agent.adapters.llm import (
    APIProviderConnectionService,
    CredentialStorageMode,
    OllamaStructuredLLMProvider,
    SessionMemorySecretStore,
)
from google_work_agent.adapters.llm.api_provider import (
    ApiStructuredLLMProvider as StructuredInferenceRuntimeRouter,
)
from google_work_agent.adapters.llm.runtime.llm_credential_router import LlmCredentialRouter
from google_work_agent.adapters.llm.runtime.llm_runtime_status_router import LlmRuntimeStatusRouter
from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter as CanonicalStructuredInferenceRuntimeRouter,
)
from google_work_agent.adapters.readiness.composite import (
    StaticLauncherProbeVerifier,
    StaticReadinessAggregator,
)
from google_work_agent.adapters.runtime import (
    BuildProfile,
    FileSettingsStore,
    SettingsPatch,
)
from google_work_agent.adapters.system.json_settings import JsonSettingsAdapter
from google_work_agent.api.app import create_app
from google_work_agent.api.container import ApiContainer
from google_work_agent.application.llm import (
    DeleteLLMApiKeyService,
    GetLLMConnectionService,
    StoreLLMApiKeyService,
)
from google_work_agent.application.llm import (
    LLMRuntimeService as _LLMRuntimeService,
)
from google_work_agent.application.llm import (
    TestLLMConnectionService as LLMConnectionTestService,
)
from google_work_agent.ports import (
    AccessDecision,
    ApiRequestContext,
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
        )
        if key in kwargs
    }
    kwargs.pop("api_provider")
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


@dataclass
class _RuntimeStatusProvider(RuntimeStatusProvider):
    settings_service: JsonSettingsAdapter
    llm_status_service: LlmRuntimeStatusRouter

    def get_summary(self) -> RuntimeSummary:
        settings = self.settings_service.get()
        api_llm, ollama, llm = self.llm_status_service.summarize_top_level(settings)
        return RuntimeSummary(
            google="CONNECTED",
            mcp="READY",
            api_llm=api_llm,
            ollama=ollama,
            deployment_profile=settings.deployment_profile,
            recovery_required_run_ids=(),
            open_run_ids=(),
            llm=llm,
        )


class _QueryStub:
    def __init__(self, runtime_status_provider: RuntimeStatusProvider) -> None:
        self._runtime_status_provider = runtime_status_provider

    def get_runtime_summary(self) -> RuntimeSummary:
        return self._runtime_status_provider.get_summary()


def test_llm_runtime_routes_mask_secrets_and_project_runtime_state(tmp_path: Path) -> None:
    clock = FakeClockPort(1_000)
    keyring = FakeKeyring()
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
    settings_service = JsonSettingsAdapter(
        store=FileSettingsStore(tmp_path / "settings" / "app-settings.json"),
        deployment_profile=BuildProfile.LOCAL_CAPABLE,
        approved_model_ids=frozenset({approved_model().model_id}),
        has_active_runs=lambda: False,
    )
    settings_service.patch(
        SettingsPatch(
            command_id="cmd-1",
            requested_runtime_mode="API_LLM",
            external_llm_consent=True,
            ollama_endpoint="http://127.0.0.1:11434",
        )
    )
    status_service = LlmRuntimeStatusRouter(
        build_profile="LOCAL_CAPABLE",
        credential_service=credential_service,
        api_connection_service=APIProviderConnectionService(api_transport),
        hardware_probe=FakeHardwareProbe(),
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
    )
    runtime_provider = _RuntimeStatusProvider(settings_service, status_service)
    runtime_service = LLMRuntimeService(
        settings_service=settings_service.get,
        status_service=status_service,
        credential_service=credential_service,
        api_provider=StructuredInferenceRuntimeRouter(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredLLMProvider(
            provider_name="ollama",
            transport=ollama_transport,
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
        ),
        router=None,
        runtime_policy=RuntimePolicy(),
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
        get_llm_connection_service=GetLLMConnectionService(
            runtime_status_service=status_service,
            settings_service=settings_service.get,
        ),
        store_llm_api_key_service=StoreLLMApiKeyService(credential_service),
        delete_llm_api_key_service=DeleteLLMApiKeyService(credential_service),
        test_llm_connection_service=LLMConnectionTestService(runtime_service),
    )

    with TestClient(create_app(container)) as client:
        stored = client.post(
            "/api/v1/llm/api-key",
            json={"api_key": "sk-test-secret", "storage_mode": CredentialStorageMode.KEYRING.value},
        )
        assert stored.status_code == 200
        assert stored.json()["credential_state"] == "KEYRING"
        assert "sk-test-secret" not in stored.text

        connection = client.get("/api/v1/llm/connection")
        assert connection.status_code == 200
        assert connection.json()["llm"]["api_provider"]["credential_state"] == "KEYRING"
        assert "sk-test-secret" not in connection.text

        runtime = client.get("/api/v1/runtime")
        assert runtime.status_code == 200
        assert runtime.json()["summary"]["llm"]["api_provider"]["credential_state"] == "KEYRING"

        tested = client.post("/api/v1/llm/test", json={})
        assert tested.status_code == 200
        assert tested.json()["llm"]["external_llm_consent"] is True
        assert tested.json()["llm"]["api_provider"]["availability"] == "AVAILABLE"

        deleted = client.delete("/api/v1/llm/api-key")
        assert deleted.status_code == 200
        assert deleted.json()["credential_state"] == "NOT_CONFIGURED"

        runtime_after_delete = client.get("/api/v1/runtime")
        runtime_summary = runtime_after_delete.json()["summary"]
        assert runtime_summary["llm"]["api_provider"]["credential_state"] == "NOT_CONFIGURED"
        assert "sk-test-secret" not in runtime_after_delete.text
