from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from tests.support.external_llm_scope import build_external_scope_gate
from tests.support.fakes import (
    FakeAPIProviderTransport,
    FakeOllamaTransport,
    FakeSchemaRepairer,
    approved_model,
)

from google_work_agent.adapters.llm.gemini.structured_inference import (
    GeminiConnectionService,
)
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
from google_work_agent.adapters.runtime import AppSettings
from google_work_agent.application.use_cases.run.project_external_llm_transfer_scope import (
    ProjectExternalLlmTransferScopeQueryV1,
)
from google_work_agent.ports.llm import (
    ActualRuntime,
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)
from google_work_agent.ports.system.contracts.external_llm_transfer_scope import (
    ExternalLlmTransferScopeV1,
)
from google_work_agent.ports.system.hardware_probe_port import HardwareProfileV1

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


@dataclass(frozen=True)
class _HardwareProbe:
    eligible: bool = True

    def probe(self) -> HardwareProfileV1:
        return HardwareProfileV1(
            schema_version=1,
            cpu_logical_cores=8,
            ram_total_bytes=16 * 1024**3,
            gpu_present=self.eligible,
            gpu_name="test-gpu" if self.eligible else None,
            vram_total_bytes=8 * 1024**3 if self.eligible else None,
            ollama_available=self.eligible,
            ollama_version="test" if self.eligible else None,
            local_runtime_eligible=self.eligible,
        )


def _status_service(
    *,
    build_profile: str,
    credential_service: LlmCredentialRouter,
    api_transport: FakeAPIProviderTransport,
    ollama_transport: FakeOllamaTransport,
) -> LlmRuntimeStatusRouter:
    return LlmRuntimeStatusRouter(
        build_profile=build_profile,
        settings_service=lambda: AppSettings(
            deployment_profile=build_profile,
            requested_runtime_mode="AUTO",
            external_llm_consent=True,
            approved_model_id=approved_model().model_id,
            ollama_endpoint="http://127.0.0.1:11434",
        ),
        credential_service=credential_service,
        api_connection_service=GeminiConnectionService(api_transport),
        ollama_probe=type(
            "_Probe",
            (),
            {
                "probe": lambda self, endpoint, approved_model: ollama_transport.probe(
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


def build_runtime(**kwargs: object) -> CanonicalStructuredInferenceRuntimeRouter:
    """Build the sole canonical structured-inference router."""
    kwargs.pop("router", None)
    router_kwargs: dict[str, Any] = {
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
        )
        if key in kwargs
    }
    router_kwargs.setdefault("hardware_probe", _HardwareProbe())
    kwargs.clear()
    checkpoint, projector = build_external_scope_gate()
    router_kwargs["checkpoint"] = checkpoint
    router = CanonicalStructuredInferenceRuntimeRouter(
        api_provider_name="generic", **cast(Any, router_kwargs)
    )

    def project_scope(
        run_id: str, source_kinds: tuple[str, ...], data_classes: tuple[str, ...]
    ) -> ExternalLlmTransferScopeV1:
        scope = projector(
            ProjectExternalLlmTransferScopeQueryV1(
                schema_version=1,
                run_id=run_id,
                source_kinds=source_kinds,
                data_classes=cast(Any, data_classes),
                occurred_at_ms=1,
            )
        )
        assert scope is not None
        return scope

    router.external_scope_projector = project_scope
    router.run_context_provider = lambda: "run-1"
    return router


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
    credential_service = LlmCredentialRouter(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=SessionMemorySecretStore(),
        session_store=SessionMemorySecretStore(),
    )
    credential_service.store_credential("generic", b"key-1", "KEYRING", "credential-op")
    settings = AppSettings(
        deployment_profile="API_ONLY",
        requested_runtime_mode="API_LLM",
        external_llm_consent=True,
    )
    service = build_runtime(
        settings_service=lambda: settings,
        status_service=_status_service(
            build_profile="API_ONLY",
            credential_service=credential_service,
            api_transport=api_transport,
            ollama_transport=ollama_transport,
        ),
        credential_service=credential_service,
        api_provider=StructuredInferenceRuntimeRouter(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredInferenceAdapter(
            provider_name="ollama",
            transport=ollama_transport,
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
        ),
        router=None,
        runtime_policy=RuntimePolicy(),
    )

    result = service.infer("API_LLM", PROMPT_REF, {"topic": "hello"}, OUTPUT_SCHEMA)

    assert result.actual_runtime == ActualRuntime.API_LLM.value
    assert result.structured_output == {"answer": "ok"}
    assert len(api_transport.invocations) == 2  # probe + invoke
    assert not ollama_transport.invocations


def test_discard_run_is_a_harmless_noop() -> None:
    """G3 RunBudgetV2: the structured-inference router does not own any per-run LLM call
    accounting (that authority moved to the checkpoint-persistent
    retry_budget/RunBudgetV2, gated by agent_kernel.ensure_llm_call_budget
    at each native subgraph node -- see test_supervisor.py and
    test_agent_kernel_budget.py). discard_run stays on the
    StructuredInferencePort contract for its workflow callers
    (Run finalize cleanup) and must not raise or affect any other run.
    """
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
    credential_service = LlmCredentialRouter(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=SessionMemorySecretStore(),
        session_store=SessionMemorySecretStore(),
    )
    credential_service.store_credential("generic", b"key-1", "KEYRING", "credential-op")
    settings = AppSettings(
        deployment_profile="API_ONLY",
        requested_runtime_mode="API_LLM",
        external_llm_consent=True,
    )
    service = build_runtime(
        settings_service=lambda: settings,
        status_service=_status_service(
            build_profile="API_ONLY",
            credential_service=credential_service,
            api_transport=api_transport,
            ollama_transport=FakeOllamaTransport(),
        ),
        credential_service=credential_service,
        api_provider=StructuredInferenceRuntimeRouter(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredInferenceAdapter(
            provider_name="ollama",
            transport=FakeOllamaTransport(),
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
        ),
        router=None,
        runtime_policy=RuntimePolicy(),
    )

    service.discard_run(run_id="run-never-started")
    result = service.infer("API_LLM", PROMPT_REF, {"topic": "hello"}, OUTPUT_SCHEMA)
    service.discard_run(run_id="run-1")

    assert result.structured_output == {"answer": "ok"}


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
    credential_service = LlmCredentialRouter(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=SessionMemorySecretStore(),
        session_store=SessionMemorySecretStore(),
    )
    credential_service.store_credential("generic", b"key-1", "KEYRING", "credential-op")
    settings = AppSettings(
        deployment_profile="LOCAL_CAPABLE",
        requested_runtime_mode="AUTO",
        external_llm_consent=True,
        ollama_endpoint="http://127.0.0.1:11434",
        approved_model_id=approved_model().model_id,
    )
    recorder = RecordingEventRecorder()
    service = build_runtime(
        settings_service=lambda: settings,
        status_service=_status_service(
            build_profile="LOCAL_CAPABLE",
            credential_service=credential_service,
            api_transport=api_transport,
            ollama_transport=ollama_transport,
        ),
        credential_service=credential_service,
        api_provider=StructuredInferenceRuntimeRouter(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredInferenceAdapter(
            provider_name="ollama",
            transport=ollama_transport,
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
        ),
        router=None,
        runtime_policy=RuntimePolicy(),
        event_recorder=recorder,
    )

    result = service.infer("AUTO", PROMPT_REF, {"topic": "hello"}, OUTPUT_SCHEMA)

    assert result.actual_runtime == ActualRuntime.API_LLM.value
    assert result.fallback_reason == LLMErrorCode.GPU_OOM.value
    assert "LLM_FALLBACK_STARTED" in recorder.events
    assert "LLM_FALLBACK_COMPLETED" in recorder.events


def test_local_gpu_mode_never_falls_back_to_api() -> None:
    api_transport = FakeAPIProviderTransport()
    ollama_transport = FakeOllamaTransport()
    ollama_transport.queued_payloads.append(
        LLMInvocationError(LLMErrorCode.PROVIDER_TIMEOUT, "local timeout")
    )
    credential_service = LlmCredentialRouter(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=SessionMemorySecretStore(),
        session_store=SessionMemorySecretStore(),
    )
    credential_service.store_credential("generic", b"key-1", "KEYRING", "credential-op")
    settings = AppSettings(
        deployment_profile="LOCAL_CAPABLE",
        requested_runtime_mode="LOCAL_GPU",
        external_llm_consent=True,
        ollama_endpoint="http://127.0.0.1:11434",
        approved_model_id=approved_model().model_id,
    )
    service = build_runtime(
        settings_service=lambda: settings,
        status_service=_status_service(
            build_profile="LOCAL_CAPABLE",
            credential_service=credential_service,
            api_transport=api_transport,
            ollama_transport=ollama_transport,
        ),
        credential_service=credential_service,
        api_provider=StructuredInferenceRuntimeRouter(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredInferenceAdapter(
            provider_name="ollama",
            transport=ollama_transport,
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
        ),
        router=None,
        runtime_policy=RuntimePolicy(),
    )

    try:
        service.infer("LOCAL_GPU", PROMPT_REF, {"topic": "hello"}, OUTPUT_SCHEMA)
    except LLMInvocationError as error:
        assert error.code is LLMErrorCode.PROVIDER_TIMEOUT
    else:
        raise AssertionError("expected local failure")
    assert len([call for call in api_transport.invocations if call["kind"] == "invoke"]) == 0


def test_local_gpu_blocked_when_hardware_not_validated() -> None:
    """LOCAL_GPU must only dispatch on a validated GPU (not merely approved+configured).

    Previously the router always set primary_runtime=LOCAL_GPU regardless of
    hardware_capability.capability_status, and _resolve_provider never
    checked it either -- NOT_VALIDATED hardware silently reached Ollama.
    """
    api_transport = FakeAPIProviderTransport()
    ollama_transport = FakeOllamaTransport()
    credential_service = LlmCredentialRouter(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=SessionMemorySecretStore(),
        session_store=SessionMemorySecretStore(),
    )
    settings = AppSettings(
        deployment_profile="LOCAL_CAPABLE",
        requested_runtime_mode="LOCAL_GPU",
        external_llm_consent=False,
        ollama_endpoint="http://127.0.0.1:11434",
        approved_model_id=approved_model().model_id,
    )
    not_validated_probe = _HardwareProbe(eligible=False)
    service = build_runtime(
        settings_service=lambda: settings,
        status_service=_status_service(
            build_profile="LOCAL_CAPABLE",
            credential_service=credential_service,
            api_transport=api_transport,
            ollama_transport=ollama_transport,
        ),
        credential_service=credential_service,
        api_provider=StructuredInferenceRuntimeRouter(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredInferenceAdapter(
            provider_name="ollama",
            transport=ollama_transport,
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
        ),
        router=None,
        runtime_policy=RuntimePolicy(),
        hardware_probe=not_validated_probe,
    )

    try:
        service.infer("LOCAL_GPU", PROMPT_REF, {"topic": "hello"}, OUTPUT_SCHEMA)
    except LLMInvocationError as error:
        assert error.code is LLMErrorCode.LOCAL_UNAVAILABLE
    else:
        raise AssertionError("expected local dispatch to be blocked by unvalidated hardware")
    assert len([call for call in ollama_transport.invocations if call["kind"] == "invoke"]) == 0


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
    credential_service = LlmCredentialRouter(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=SessionMemorySecretStore(),
        session_store=SessionMemorySecretStore(),
    )
    credential_service.store_credential("generic", b"key-1", "KEYRING", "credential-op")
    repairer = FakeSchemaRepairer(repaired_output={"answer": "fixed"})
    settings = AppSettings(
        deployment_profile="API_ONLY",
        requested_runtime_mode="API_LLM",
        external_llm_consent=True,
    )
    service = build_runtime(
        settings_service=lambda: settings,
        status_service=_status_service(
            build_profile="API_ONLY",
            credential_service=credential_service,
            api_transport=api_transport,
            ollama_transport=FakeOllamaTransport(),
        ),
        credential_service=credential_service,
        api_provider=StructuredInferenceRuntimeRouter(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredInferenceAdapter(
            provider_name="ollama",
            transport=FakeOllamaTransport(),
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
        ),
        router=None,
        runtime_policy=RuntimePolicy(structured_output_repair_budget=1),
        schema_repairer=repairer,
    )

    result = service.infer("API_LLM", PROMPT_REF, {"topic": "hello"}, OUTPUT_SCHEMA)

    assert result.structured_output == {"answer": "fixed"}
    # StructuredInferenceResultV1 deliberately exposes only the exact
    # canonical result surface; the repair attempt is proved by the repairer.
    assert len(repairer.calls) == 1


def test_application_semantic_validation_does_not_create_a_second_router_repair_path() -> None:
    api_transport = FakeAPIProviderTransport()
    api_transport.queued_payloads.append(
        ProviderResponsePayload(
            content={"answer": "wrong-value"},
            model="api-model",
            provider_request_id="req-5",
            input_tokens=5,
            output_tokens=4,
            latency_ms=10,
        )
    )
    credential_service = LlmCredentialRouter(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=SessionMemorySecretStore(),
        session_store=SessionMemorySecretStore(),
    )
    credential_service.store_credential("generic", b"key-1", "KEYRING", "credential-op")
    repairer = FakeSchemaRepairer(repaired_output={"answer": "correct-value"})
    settings = AppSettings(
        deployment_profile="API_ONLY",
        requested_runtime_mode="API_LLM",
        external_llm_consent=True,
    )
    service = build_runtime(
        settings_service=lambda: settings,
        status_service=_status_service(
            build_profile="API_ONLY",
            credential_service=credential_service,
            api_transport=api_transport,
            ollama_transport=FakeOllamaTransport(),
        ),
        credential_service=credential_service,
        api_provider=StructuredInferenceRuntimeRouter(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredInferenceAdapter(
            provider_name="ollama",
            transport=FakeOllamaTransport(),
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
        ),
        router=None,
        runtime_policy=RuntimePolicy(structured_output_repair_budget=1),
        schema_repairer=repairer,
    )

    def semantic_validate(candidate: object) -> object:
        if not isinstance(candidate, dict) or candidate.get("answer") != "correct-value":
            raise ValueError("$.answer must be 'correct-value'")
        return candidate

    with pytest.raises(ValueError, match="correct-value"):
        semantic_validate(
            service.infer(
                "API_LLM", PROMPT_REF, {"topic": "hello"}, OUTPUT_SCHEMA
            ).structured_output
        )

    assert repairer.calls == []


def test_semantic_validate_failure_without_repairer_raises_once_no_repair_attempt() -> None:
    api_transport = FakeAPIProviderTransport()
    api_transport.queued_payloads.append(
        ProviderResponsePayload(
            content={"answer": "wrong-value"},
            model="api-model",
            provider_request_id="req-6",
            input_tokens=5,
            output_tokens=4,
            latency_ms=10,
        )
    )
    credential_service = LlmCredentialRouter(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=SessionMemorySecretStore(),
        session_store=SessionMemorySecretStore(),
    )
    credential_service.store_credential("generic", b"key-1", "KEYRING", "credential-op")
    settings = AppSettings(
        deployment_profile="API_ONLY",
        requested_runtime_mode="API_LLM",
        external_llm_consent=True,
    )
    service = build_runtime(
        settings_service=lambda: settings,
        status_service=_status_service(
            build_profile="API_ONLY",
            credential_service=credential_service,
            api_transport=api_transport,
            ollama_transport=FakeOllamaTransport(),
        ),
        credential_service=credential_service,
        api_provider=StructuredInferenceRuntimeRouter(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredInferenceAdapter(
            provider_name="ollama",
            transport=FakeOllamaTransport(),
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
        ),
        router=None,
        runtime_policy=RuntimePolicy(),
    )

    def semantic_validate(candidate: object) -> object:
        raise ValueError("always invalid")

    with pytest.raises(ValueError, match="always invalid"):
        semantic_validate(
            service.infer(
                "API_LLM", PROMPT_REF, {"topic": "hello"}, OUTPUT_SCHEMA
            ).structured_output
        )
    invoke_calls = [c for c in api_transport.invocations if c["kind"] == "invoke"]
    assert len(invoke_calls) == 1
