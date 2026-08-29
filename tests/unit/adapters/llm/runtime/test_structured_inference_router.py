from __future__ import annotations

from dataclasses import dataclass

import pytest
from tests.support.external_llm_scope import ExternalScopeCheckpoint

from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter,
)
from google_work_agent.adapters.runtime import AppSettings
from google_work_agent.ports.llm import (
    ActualRuntime,
    ApprovedModelInfo,
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)
from google_work_agent.ports.llm.llm_credential_port import LlmCredentialStatusV1
from google_work_agent.ports.llm.llm_runtime_status_port import LlmRuntimeStatusV1
from google_work_agent.ports.system.contracts.external_llm_transfer_scope import (
    ExternalLlmTransferScopeV1,
)
from google_work_agent.ports.system.hardware_probe_port import HardwareProfileV1

PROMPT = PromptReference(
    "1", "test", "1", "hash", "role", "graph", "node", "state", "test", "1", "1"
)
SCHEMA = OutputSchemaDefinition(
    "1",
    {
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
        "additionalProperties": False,
    },
)


@dataclass
class _Provider:
    runtime: ActualRuntime = ActualRuntime.API_LLM
    calls: int = 0
    checkpoint_to_stale: ExternalScopeCheckpoint | None = None
    failure: LLMInvocationError | None = None

    @property
    def provider_name(self) -> str:
        return "api" if self.runtime is ActualRuntime.API_LLM else "ollama"

    def invoke_structured(self, **kwargs: object) -> ProviderResponsePayload:
        del kwargs
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        if self.checkpoint_to_stale is not None:
            self.checkpoint_to_stale.scope = _scope(scope_hash="stale-after-first-call")
            return ProviderResponsePayload({}, "model", None, 1, 1, 1)
        return ProviderResponsePayload({"answer": "ok"}, "model", None, 1, 1, 1)


class _Status:
    def get_status(self, provider: str) -> LlmRuntimeStatusV1:
        return LlmRuntimeStatusV1(1, provider, True, "READY", "model", None)

    def get_approved_model(self, model_id: str) -> ApprovedModelInfo | None:
        return ApprovedModelInfo(model_id, "OLLAMA", "1", "1")


class _Credential:
    def get_credential_status(self, provider: str) -> LlmCredentialStatusV1:
        return LlmCredentialStatusV1(1, provider, True, "KEYRING", "VALID")

    def read_secret(self, provider: str) -> bytes:
        del provider
        return b"key"


class _Hardware:
    def probe(self) -> HardwareProfileV1:
        return HardwareProfileV1(1, 8, 16 * 1024**3, True, "gpu", 8 * 1024**3, True, "1", True)


@dataclass
class _Repairer:
    calls: int = 0

    def repair(self, **kwargs: object) -> object:
        del kwargs
        self.calls += 1
        return {"answer": "repaired"}


def _scope(*, scope_hash: str = "scope-hash") -> ExternalLlmTransferScopeV1:
    return ExternalLlmTransferScopeV1(
        1, "run-1", 1, scope_hash, ("user_request",), ("USER_REQUEST",)
    )


def _router(
    *,
    checkpoint: ExternalScopeCheckpoint,
    api: _Provider,
    local: _Provider | None = None,
    consent: bool = True,
    repairer: _Repairer | None = None,
) -> StructuredInferenceRuntimeRouter:
    settings = AppSettings(
        deployment_profile="LOCAL_CAPABLE",
        requested_runtime_mode="API_LLM",
        external_llm_consent=consent,
        approved_model_id="model",
        ollama_endpoint="http://127.0.0.1:11434",
    )
    local_provider = local or _Provider(runtime=ActualRuntime.LOCAL_GPU)
    return StructuredInferenceRuntimeRouter(
        settings_service=lambda: settings,
        status_service=_Status(),  # type: ignore[arg-type]
        credential_service=_Credential(),  # type: ignore[arg-type]
        hardware_probe=_Hardware(),
        api_provider_name="api",
        api_provider=api,
        ollama_provider_factory=lambda _model, _settings: local_provider,
        runtime_policy=RuntimePolicy(),
        checkpoint=checkpoint,  # type: ignore[arg-type]
        schema_repairer=repairer,
    )


@pytest.mark.parametrize("published", [None, _scope(scope_hash="different")])
def test_api_provider_is_not_called_without_exact_published_scope(
    published: ExternalLlmTransferScopeV1 | None,
) -> None:
    checkpoint = ExternalScopeCheckpoint(scope=published)
    provider = _Provider()
    with pytest.raises(LLMInvocationError):
        _router(checkpoint=checkpoint, api=provider).infer(
            "API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA, _scope()
        )
    assert provider.calls == 0


def test_exact_published_scope_allows_one_api_call() -> None:
    scope = _scope()
    checkpoint = ExternalScopeCheckpoint(scope=scope)
    provider = _Provider()
    result = _router(checkpoint=checkpoint, api=provider).infer(
        "API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA, scope
    )
    assert result.structured_output == {"answer": "ok"}
    assert provider.calls == 1


def test_consent_revoke_blocks_api_call_even_with_exact_scope() -> None:
    scope = _scope()
    checkpoint = ExternalScopeCheckpoint(scope=scope)
    provider = _Provider()
    with pytest.raises(LLMInvocationError) as captured:
        _router(checkpoint=checkpoint, api=provider, consent=False).infer(
            "API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA, scope
        )
    assert captured.value.code is LLMErrorCode.CONSENT_REQUIRED
    assert provider.calls == 0


def test_scope_is_rechecked_before_api_schema_repair_call() -> None:
    scope = _scope()
    checkpoint = ExternalScopeCheckpoint(scope=scope)
    provider = _Provider(checkpoint_to_stale=checkpoint)
    repairer = _Repairer()
    with pytest.raises(LLMInvocationError):
        _router(checkpoint=checkpoint, api=provider, repairer=repairer).infer(
            "API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA, scope
        )
    assert provider.calls == 1
    assert repairer.calls == 0


def test_auto_fallback_does_not_call_api_without_published_scope() -> None:
    checkpoint = ExternalScopeCheckpoint()
    api = _Provider()
    local = _Provider(
        runtime=ActualRuntime.LOCAL_GPU,
        failure=LLMInvocationError(LLMErrorCode.GPU_OOM, "oom"),
    )
    with pytest.raises(LLMInvocationError):
        _router(checkpoint=checkpoint, api=api, local=local).infer(
            "AUTO", PROMPT, {"user_request": "hello"}, SCHEMA, _scope()
        )
    assert local.calls == 1
    assert api.calls == 0
