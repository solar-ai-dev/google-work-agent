from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
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
    CredentialStorageMode,
    DeterministicLLMRuntimeRouter,
    OllamaStructuredLLMProvider,
    SessionMemorySecretStore,
)
from google_work_agent.adapters.llm.runtime.llm_credential_router import LlmCredentialRouter
from google_work_agent.adapters.llm.runtime.llm_runtime_status_router import LlmRuntimeStatusRouter
from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter,
)
from google_work_agent.adapters.runtime import AppSettings
from google_work_agent.application.llm import LLMRuntimeService
from google_work_agent.ports import (
    ActualRuntime,
    HardwareCapabilityStatus,
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)
from google_work_agent.ports.observability_events import ObservabilityContext

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


def _manifest(tmp_path: Path) -> Path:
    """Isolated Prompt Runtime Input Contract for this module's synthetic
    PROMPT_REF ("node.plan") -- these tests exercise LLMRuntimeService
    routing/fallback/repair mechanics generically and were never meant to
    be validated against the real production Product Prompt contract."""
    agent_dir = tmp_path / "prompts" / "agent"
    contract_dir = agent_dir / "contracts"
    contract_dir.mkdir(parents=True, exist_ok=True)
    manifest = agent_dir / "prompt-manifest-v1.0.0.json"
    manifest.write_text(
        json.dumps({"runtime_input_contract": "prompts/agent/contracts/input.json"}),
        encoding="utf-8",
    )
    (contract_dir / "input.json").write_text(
        json.dumps(
            {
                "forbidden_runtime_fields": [],
                "slots": {"node.plan": {"allowed_root_fields": ["topic"]}},
            }
        ),
        encoding="utf-8",
    )
    return manifest


@dataclass
class RecordingEventRecorder:
    events: list[str] = field(default_factory=list)

    def record(self, **kwargs: object) -> None:
        self.events.append(str(kwargs["event_name"]))


def _status_service(
    *,
    build_profile: str,
    credential_service: LlmCredentialRouter,
    api_transport: FakeAPIProviderTransport,
    ollama_transport: FakeOllamaTransport,
    hardware_probe: FakeHardwareProbe | None = None,
) -> LlmRuntimeStatusRouter:
    return LlmRuntimeStatusRouter(
        build_profile=build_profile,
        credential_service=credential_service,
        api_connection_service=APIProviderConnectionService(api_transport),
        hardware_probe=hardware_probe or FakeHardwareProbe(),
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


def test_api_only_invokes_external_provider(tmp_path: Path) -> None:
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
        api_provider=StructuredInferenceRuntimeRouter(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
            prompt_manifest_path=_manifest(tmp_path),
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredLLMProvider(  # noqa: ARG005
            provider_name="ollama",
            transport=ollama_transport,
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
            prompt_manifest_path=_manifest(tmp_path),
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
    assert result.provider_calls_consumed == 1
    assert len(api_transport.invocations) == 2  # probe + invoke
    assert not ollama_transport.invocations


def test_discard_run_is_a_harmless_noop(tmp_path: Path) -> None:
    """G3 RunBudgetV1: LLMRuntimeService no longer owns any per-run LLM call
    accounting (that authority moved to the checkpoint-persistent
    retry_budget/RunBudgetV1, gated by agent_kernel.ensure_llm_call_budget
    at each native subgraph node -- see test_supervisor.py and
    test_agent_kernel_budget.py). discard_run stays on the
    StructuredLLMRuntime Protocol purely for its existing runtime.py caller
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
            ollama_transport=FakeOllamaTransport(),
        ),
        credential_service=credential_service,
        api_provider=StructuredInferenceRuntimeRouter(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
            prompt_manifest_path=_manifest(tmp_path),
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredLLMProvider(  # noqa: ARG005
            provider_name="ollama",
            transport=FakeOllamaTransport(),
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
            prompt_manifest_path=_manifest(tmp_path),
        ),
        router=DeterministicLLMRuntimeRouter(),
        runtime_policy=RuntimePolicy(),
    )

    service.discard_run(run_id="run-never-started")
    result = service.invoke_structured(
        prompt_ref=PROMPT_REF,
        prompt_input={"topic": "hello"},
        output_schema=OUTPUT_SCHEMA,
        trace_context=ObservabilityContext(run_id="run-1", llm_call_id="llm-1"),
    )
    service.discard_run(run_id="run-1")

    assert result.structured_output == {"answer": "ok"}


def test_auto_falls_back_once_after_local_gpu_failure(tmp_path: Path) -> None:
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
        api_provider=StructuredInferenceRuntimeRouter(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
            prompt_manifest_path=_manifest(tmp_path),
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredLLMProvider(
            provider_name="ollama",
            transport=ollama_transport,
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
            prompt_manifest_path=_manifest(tmp_path),
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


def test_local_gpu_mode_never_falls_back_to_api(tmp_path: Path) -> None:
    api_transport = FakeAPIProviderTransport()
    ollama_transport = FakeOllamaTransport()
    ollama_transport.queued_payloads.append(
        LLMInvocationError(LLMErrorCode.PROVIDER_TIMEOUT, "local timeout")
    )
    credential_service = LlmCredentialRouter(
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
        api_provider=StructuredInferenceRuntimeRouter(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
            prompt_manifest_path=_manifest(tmp_path),
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredLLMProvider(
            provider_name="ollama",
            transport=ollama_transport,
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
            prompt_manifest_path=_manifest(tmp_path),
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
        keyring_store=FakeKeyring(),
        session_store=SessionMemorySecretStore(),
    )
    settings = AppSettings(
        deployment_profile="LOCAL_CAPABLE",
        requested_runtime_mode="LOCAL_GPU",
        external_llm_consent=False,
        ollama_endpoint="http://127.0.0.1:11434",
        approved_model_id=approved_model().model_id,
    )
    not_validated_probe = FakeHardwareProbe(
        capability=replace(
            FakeHardwareProbe().capability,
            capability_status=HardwareCapabilityStatus.NOT_VALIDATED,
        )
    )
    service = LLMRuntimeService(
        settings_service=lambda: settings,
        status_service=_status_service(
            build_profile="LOCAL_CAPABLE",
            credential_service=credential_service,
            api_transport=api_transport,
            ollama_transport=ollama_transport,
            hardware_probe=not_validated_probe,
        ),
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
        router=DeterministicLLMRuntimeRouter(),
        runtime_policy=RuntimePolicy(),
    )

    try:
        service.invoke_structured(
            prompt_ref=PROMPT_REF,
            prompt_input={"topic": "hello"},
            output_schema=OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(run_id="run-1", llm_call_id="llm-hw-1"),
        )
    except LLMInvocationError as error:
        assert error.code is LLMErrorCode.LOCAL_UNAVAILABLE
    else:
        raise AssertionError("expected local dispatch to be blocked by unvalidated hardware")
    assert len([call for call in ollama_transport.invocations if call["kind"] == "invoke"]) == 0


def test_schema_repair_is_limited_to_one_attempt(tmp_path: Path) -> None:
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
        api_provider=StructuredInferenceRuntimeRouter(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
            prompt_manifest_path=_manifest(tmp_path),
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredLLMProvider(
            provider_name="ollama",
            transport=FakeOllamaTransport(),
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
            prompt_manifest_path=_manifest(tmp_path),
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
    # G3 RunBudgetV1: provider_calls_consumed now reflects the real attempt
    # count (INITIAL + SCHEMA_REPAIR), matching structured_output_attempts,
    # instead of the previous hardcoded 1 -- this is what lets a node's
    # retry_budget accounting count the repair call too.
    assert result.provider_calls_consumed == 2
    assert len(repairer.calls) == 1


def test_semantic_validate_failure_is_repaired_through_the_same_boundary(tmp_path: Path) -> None:
    """A candidate that satisfies output_schema's JSON-shape but fails a
    caller-supplied semantic_validate (e.g. work_analysis's cross-reference
    checks) must share the exact same repair call and one-attempt budget as
    a JSON-schema-shape failure -- not escape uncaught."""
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
        keyring_store=FakeKeyring(),
        session_store=SessionMemorySecretStore(),
    )
    credential_service.store(api_key="key-1", mode=CredentialStorageMode.KEYRING)
    repairer = FakeSchemaRepairer(repaired_output={"answer": "correct-value"})
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
        api_provider=StructuredInferenceRuntimeRouter(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
            prompt_manifest_path=_manifest(tmp_path),
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredLLMProvider(
            provider_name="ollama",
            transport=FakeOllamaTransport(),
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
            prompt_manifest_path=_manifest(tmp_path),
        ),
        router=DeterministicLLMRuntimeRouter(),
        runtime_policy=RuntimePolicy(structured_output_repair_budget=1),
        schema_repairer=repairer,
    )

    def semantic_validate(candidate: object) -> object:
        if not isinstance(candidate, dict) or candidate.get("answer") != "correct-value":
            raise ValueError("$.answer must be 'correct-value'")
        return candidate

    result = service.invoke_structured(
        prompt_ref=PROMPT_REF,
        prompt_input={"topic": "hello"},
        output_schema=OUTPUT_SCHEMA,
        trace_context=ObservabilityContext(run_id="run-2", llm_call_id="llm-5"),
        semantic_validate=semantic_validate,
    )

    assert result.structured_output == {"answer": "correct-value"}
    assert result.structured_output_attempts == 2
    assert len(repairer.calls) == 1
    assert repairer.calls[0]["validator_errors"] == ["$.answer must be 'correct-value'"]


def test_semantic_validate_failure_without_repairer_raises_once_no_repair_attempt(
    tmp_path: Path,
) -> None:
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
            ollama_transport=FakeOllamaTransport(),
        ),
        credential_service=credential_service,
        api_provider=StructuredInferenceRuntimeRouter(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
            prompt_manifest_path=_manifest(tmp_path),
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredLLMProvider(
            provider_name="ollama",
            transport=FakeOllamaTransport(),
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
            prompt_manifest_path=_manifest(tmp_path),
        ),
        router=DeterministicLLMRuntimeRouter(),
        runtime_policy=RuntimePolicy(),
    )

    def semantic_validate(candidate: object) -> object:
        raise ValueError("always invalid")

    with pytest.raises(LLMInvocationError) as excinfo:
        service.invoke_structured(
            prompt_ref=PROMPT_REF,
            prompt_input={"topic": "hello"},
            output_schema=OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(run_id="run-3", llm_call_id="llm-6"),
            semantic_validate=semantic_validate,
        )
    assert excinfo.value.code is LLMErrorCode.OUTPUT_SCHEMA_INVALID
    invoke_calls = [c for c in api_transport.invocations if c["kind"] == "invoke"]
    assert len(invoke_calls) == 1
