from __future__ import annotations

from dataclasses import dataclass, field

from tests.support.fakes import (
    FakeAPIProviderTransport,
    FakeHardwareProbe,
    FakeKeyring,
    FakeOllamaTransport,
    FakeSchemaRepairer,
    approved_model,
)

from google_work_agent.adapters.llm import (
    APIProviderConnectionService,
    ApiStructuredLLMProvider,
    CredentialStorageMode,
    DeterministicLLMRuntimeRouter,
    LLMCredentialService,
    LLMRuntimeStatusService,
    OllamaStructuredLLMProvider,
    SessionMemorySecretStore,
)
from google_work_agent.adapters.runtime import AppSettings
from google_work_agent.application.llm import LLMRuntimeService
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.ports import (
    ActualRuntime,
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)

PROMPT_REF = PromptReference(
    prompt_bundle_version="1",
    prompt_id="node.plan",
    prompt_version="1",
    content_hash="hash-1",
    agent_role="planner",
    subgraph_name="main",
    node_name="plan",
    node_state="draft",
    purpose="test",
    input_schema_version="1",
    output_schema_version="1",
)
OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="1",
    json_schema={
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
        "additionalProperties": False,
    },
)


@dataclass
class RecordingEventRecorder:
    events: list[str] = field(default_factory=list)

    def record(self, **kwargs: object) -> None:
        self.events.append(str(kwargs["event_name"]))


def _status_service(
    *,
    build_profile: str,
    credential_service: LLMCredentialService,
    api_transport: FakeAPIProviderTransport,
    ollama_transport: FakeOllamaTransport,
) -> LLMRuntimeStatusService:
    return LLMRuntimeStatusService(
        build_profile=build_profile,
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


def test_api_only_invokes_external_provider() -> None:
    api_transport = FakeAPIProviderTransport()
    api_transport.queued_payloads.append(
        ProviderResponsePayload(
            content={"answer": "ok"},
            model="api-model",
            provider_request_id="req-1",
            input_tokens=10,
            output_tokens=5,
            latency_ms=20,
        )
    )
    ollama_transport = FakeOllamaTransport()
    credential_service = LLMCredentialService(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=FakeKeyring(),
        session_store=SessionMemorySecretStore(),
    )
    credential_service.store(api_key="key-1", mode=CredentialStorageMode.KEYRING)
    settings = AppSettings(
        deployment_profile="API_ONLY",
        requested_runtime_mode="API_LLM",
        external_llm_consent=True,
    )
    service = LLMRuntimeService(
        settings_service=lambda: settings,
        status_service=_status_service(
            build_profile="API_ONLY",
            credential_service=credential_service,
            api_transport=api_transport,
            ollama_transport=ollama_transport,
        ),
        credential_service=credential_service,
        api_provider=ApiStructuredLLMProvider(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredLLMProvider(  # noqa: ARG005
            provider_name="ollama",
            transport=ollama_transport,
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
        ),
        router=DeterministicLLMRuntimeRouter(),
        runtime_policy=RuntimePolicy(),
    )

    result = service.invoke_structured(
        prompt_ref=PROMPT_REF,
        prompt_input={"topic": "hello"},
        output_schema=OUTPUT_SCHEMA,
        trace_context=ObservabilityContext(run_id="run-1", llm_call_id="llm-1"),
    )

    assert result.actual_runtime is ActualRuntime.API_LLM
    assert result.structured_output == {"answer": "ok"}
    assert len(api_transport.invocations) == 2  # probe + invoke
    assert not ollama_transport.invocations


def test_auto_falls_back_once_after_local_gpu_failure() -> None:
    api_transport = FakeAPIProviderTransport()
    api_transport.queued_payloads.append(
        ProviderResponsePayload(
            content={"answer": "api-fallback"},
            model="api-model",
            provider_request_id="req-2",
            input_tokens=11,
            output_tokens=6,
            latency_ms=25,
        )
    )
    ollama_transport = FakeOllamaTransport()
    ollama_transport.queued_payloads.append(
        LLMInvocationError(LLMErrorCode.GPU_OOM, "gpu oom", fallback_reason="GPU_OOM")
    )
    credential_service = LLMCredentialService(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=FakeKeyring(),
        session_store=SessionMemorySecretStore(),
    )
    credential_service.store(api_key="key-1", mode=CredentialStorageMode.KEYRING)
    settings = AppSettings(
        deployment_profile="LOCAL_CAPABLE",
        requested_runtime_mode="AUTO",
        external_llm_consent=True,
        ollama_endpoint="http://127.0.0.1:11434",
        approved_model_id=approved_model().model_id,
    )
    recorder = RecordingEventRecorder()
    service = LLMRuntimeService(
        settings_service=lambda: settings,
        status_service=_status_service(
            build_profile="LOCAL_CAPABLE",
            credential_service=credential_service,
            api_transport=api_transport,
            ollama_transport=ollama_transport,
        ),
        credential_service=credential_service,
        api_provider=ApiStructuredLLMProvider(
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
        router=DeterministicLLMRuntimeRouter(),
        runtime_policy=RuntimePolicy(),
        event_recorder=recorder,
    )

    result = service.invoke_structured(
        prompt_ref=PROMPT_REF,
        prompt_input={"topic": "hello"},
        output_schema=OUTPUT_SCHEMA,
        trace_context=ObservabilityContext(run_id="run-1", llm_call_id="llm-2"),
    )

    assert result.actual_runtime is ActualRuntime.API_LLM
    assert result.fallback_reason == LLMErrorCode.GPU_OOM.value
    assert "LLM_FALLBACK_STARTED" in recorder.events
    assert "LLM_FALLBACK_COMPLETED" in recorder.events


def test_local_gpu_mode_never_falls_back_to_api() -> None:
    api_transport = FakeAPIProviderTransport()
    ollama_transport = FakeOllamaTransport()
    ollama_transport.queued_payloads.append(
        LLMInvocationError(LLMErrorCode.PROVIDER_TIMEOUT, "local timeout")
    )
    credential_service = LLMCredentialService(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=FakeKeyring(),
        session_store=SessionMemorySecretStore(),
    )
    credential_service.store(api_key="key-1", mode=CredentialStorageMode.KEYRING)
    settings = AppSettings(
        deployment_profile="LOCAL_CAPABLE",
        requested_runtime_mode="LOCAL_GPU",
        external_llm_consent=True,
        ollama_endpoint="http://127.0.0.1:11434",
        approved_model_id=approved_model().model_id,
    )
    service = LLMRuntimeService(
        settings_service=lambda: settings,
        status_service=_status_service(
            build_profile="LOCAL_CAPABLE",
            credential_service=credential_service,
            api_transport=api_transport,
            ollama_transport=ollama_transport,
        ),
        credential_service=credential_service,
        api_provider=ApiStructuredLLMProvider(
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
        router=DeterministicLLMRuntimeRouter(),
        runtime_policy=RuntimePolicy(),
    )

    try:
        service.invoke_structured(
            prompt_ref=PROMPT_REF,
            prompt_input={"topic": "hello"},
            output_schema=OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(run_id="run-1", llm_call_id="llm-3"),
        )
    except LLMInvocationError as error:
        assert error.code is LLMErrorCode.PROVIDER_TIMEOUT
    else:
        raise AssertionError("expected local failure")
    assert len([call for call in api_transport.invocations if call["kind"] == "invoke"]) == 0


def test_schema_repair_is_limited_to_one_attempt() -> None:
    api_transport = FakeAPIProviderTransport()
    api_transport.queued_payloads.append(
        ProviderResponsePayload(
            content={"wrong": "shape"},
            model="api-model",
            provider_request_id="req-4",
            input_tokens=5,
            output_tokens=4,
            latency_ms=10,
        )
    )
    credential_service = LLMCredentialService(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=FakeKeyring(),
        session_store=SessionMemorySecretStore(),
    )
    credential_service.store(api_key="key-1", mode=CredentialStorageMode.KEYRING)
    repairer = FakeSchemaRepairer(repaired_output={"answer": "fixed"})
    settings = AppSettings(
        deployment_profile="API_ONLY",
        requested_runtime_mode="API_LLM",
        external_llm_consent=True,
    )
    service = LLMRuntimeService(
        settings_service=lambda: settings,
        status_service=_status_service(
            build_profile="API_ONLY",
            credential_service=credential_service,
            api_transport=api_transport,
            ollama_transport=FakeOllamaTransport(),
        ),
        credential_service=credential_service,
        api_provider=ApiStructuredLLMProvider(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredLLMProvider(
            provider_name="ollama",
            transport=FakeOllamaTransport(),
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
        ),
        router=DeterministicLLMRuntimeRouter(),
        runtime_policy=RuntimePolicy(structured_output_repair_budget=1),
        schema_repairer=repairer,
    )

    result = service.invoke_structured(
        prompt_ref=PROMPT_REF,
        prompt_input={"topic": "hello"},
        output_schema=OUTPUT_SCHEMA,
        trace_context=ObservabilityContext(run_id="run-1", llm_call_id="llm-4"),
    )

    assert result.structured_output == {"answer": "fixed"}
    assert result.structured_output_attempts == 2
    assert len(repairer.calls) == 1
