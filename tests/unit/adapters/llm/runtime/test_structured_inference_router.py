from __future__ import annotations

from dataclasses import dataclass, replace

import pytest
from tests.support.external_llm_scope import ExternalScopeCheckpoint
from tests.support.llm_runtime import runtime_selection, settings_view

from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter,
)
from google_work_agent.ports.llm.llm_credential_port import LlmCredentialStatus
from google_work_agent.ports.llm.llm_runtime_status_port import LlmProviderRuntimeStatus
from google_work_agent.ports.llm.structured_inference_contracts import (
    ActualRuntime,
    ApprovedModelInfo,
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
    def get_status(self, provider: str) -> LlmProviderRuntimeStatus:
        return LlmProviderRuntimeStatus(1, provider, True, "READY", "model", None)

    def get_approved_model(self, model_id: str) -> ApprovedModelInfo | None:
        return ApprovedModelInfo(model_id, "OLLAMA", "1", "1")

    def get_selected_model(self) -> ApprovedModelInfo:
        return ApprovedModelInfo("qwen3.5:9b", "OLLAMA", "1", "1")

    def get_model_for_prompt(self, prompt_id: str) -> ApprovedModelInfo:
        model_id = (
            "qwen3.5:4b"
            if prompt_id == "request_understanding.identify_goal"
            else "qwen3.5:9b"
        )
        return ApprovedModelInfo(model_id, "OLLAMA", "1", "1")


class _Credential:
    def get_credential_status(self, provider: str) -> LlmCredentialStatus:
        return LlmCredentialStatus(1, provider, True, "KEYRING", "VALID")

    def read_secret(self, provider: str) -> bytes:
        del provider
        return b"key"


class _Hardware:
    def probe(self) -> HardwareProfileV1:
        return HardwareProfileV1(
            1,
            8,
            16 * 1024**3,
            True,
            "gpu",
            8 * 1024**3,
            True,
            "1",
            True,
            "WINDOWS",
            "AMD64",
            (),
        )


@dataclass
class _Repairer:
    calls: int = 0

    def repair(self, **kwargs: object) -> object:
        del kwargs
        self.calls += 1
        return {"answer": "repaired"}


def _scope(*, scope_hash: str = "scope-hash") -> ExternalLlmTransferScopeV1:
    return ExternalLlmTransferScopeV1(1, "run-1", 1, scope_hash, ["user_request"], ["USER_REQUEST"])


def _router(
    *,
    checkpoint: ExternalScopeCheckpoint,
    api: _Provider,
    local: _Provider | None = None,
    consent: bool = True,
    repairer: _Repairer | None = None,
    deployment_profile: str = "LOCAL_CAPABLE",
) -> StructuredInferenceRuntimeRouter:
    settings = settings_view(
        preferred_llm_mode="API_LLM", external_llm_consent=consent
    )
    selection = runtime_selection(
        deployment_profile=deployment_profile,
        model=(
            ApprovedModelInfo("model", "OLLAMA", "1", "1")
            if deployment_profile == "LOCAL_CAPABLE"
            else None
        ),
    )
    local_provider = local or _Provider(runtime=ActualRuntime.LOCAL_GPU)
    return StructuredInferenceRuntimeRouter(
        settings_service=lambda: settings,
        runtime_selection=selection,
        status_service=_Status(),  # type: ignore[arg-type]
        credential_service=_Credential(),  # type: ignore[arg-type]
        hardware_probe=_Hardware(),
        api_provider_name="api",
        api_provider=api,
        ollama_provider_factory=lambda _model: local_provider,
        runtime_policy=RuntimePolicy(),
        checkpoint=checkpoint,  # type: ignore[arg-type]
        schema_repairer=repairer,
        run_context_provider=lambda: "run-1",
        external_scope_projector=lambda _run_id, _source_kinds, _data_classes: _scope(),
    )


def test_api_only_local_request__fails_before__either_provider_dispatch() -> None:
    checkpoint = ExternalScopeCheckpoint(scope=_scope())
    api = _Provider()
    local = _Provider(runtime=ActualRuntime.LOCAL_GPU)
    router = _router(
        checkpoint=checkpoint,
        api=api,
        local=local,
        deployment_profile="API_ONLY",
    )

    with pytest.raises(LLMInvocationError) as raised:
        router.infer("LOCAL_GPU", PROMPT, {"user_request": "hello"}, SCHEMA)

    assert raised.value.code is LLMErrorCode.RUNTIME_MODE_BLOCKED
    assert api.calls == 0
    assert local.calls == 0


def test_local_request__uses_profile__model_for_prompt() -> None:
    checkpoint = ExternalScopeCheckpoint(scope=_scope())
    local = _Provider(runtime=ActualRuntime.LOCAL_GPU)
    router = _router(checkpoint=checkpoint, api=_Provider(), local=local)
    selected: list[str] = []
    router.ollama_provider_factory = lambda model: selected.append(model.model_id) or local

    router.infer(
        "LOCAL_GPU",
        replace(PROMPT, prompt_id="request_understanding.identify_goal"),
        {"user_request": "hello"},
        SCHEMA,
    )

    assert selected == ["qwen3.5:4b"]
    assert local.calls == 1


@pytest.mark.parametrize("published", [None, _scope(scope_hash="different")])
def test_api_provider_is__not_called_without__exact_published_scope(
    published: ExternalLlmTransferScopeV1 | None,
) -> None:
    checkpoint = ExternalScopeCheckpoint(scope=published)
    provider = _Provider()
    with pytest.raises(LLMInvocationError):
        _router(checkpoint=checkpoint, api=provider).infer(
            "API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA
        )
    assert provider.calls == 0


def test_exact_published__scope_allows__one_api_call() -> None:
    scope = _scope()
    checkpoint = ExternalScopeCheckpoint(scope=scope)
    provider = _Provider()
    result = _router(checkpoint=checkpoint, api=provider).infer(
        "API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA
    )
    assert result.structured_output == {"answer": "ok"}
    assert provider.calls == 1


def test_runtime_circuit_callbacks__guard_and_record__the_selected_leaf() -> None:
    scope = _scope()
    checkpoint = ExternalScopeCheckpoint(scope=scope)
    provider = _Provider()
    router = _router(checkpoint=checkpoint, api=provider)
    events: list[tuple[str, ActualRuntime, str | None]] = []
    router.before_runtime_dispatch = lambda runtime: events.append(("guard", runtime, None))
    router.record_runtime_result = lambda runtime, error: events.append(("result", runtime, error))

    router.infer("API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA)

    assert events == [
        ("guard", ActualRuntime.API_LLM, None),
        ("result", ActualRuntime.API_LLM, None),
    ]


def test_runtime_circuit__guard_blocks__before_provider_dispatch() -> None:
    scope = _scope()
    checkpoint = ExternalScopeCheckpoint(scope=scope)
    provider = _Provider()
    router = _router(checkpoint=checkpoint, api=provider)

    def block(_runtime: ActualRuntime) -> None:
        raise LLMInvocationError(LLMErrorCode.PROVIDER_UNAVAILABLE, "circuit open")

    router.before_runtime_dispatch = block

    with pytest.raises(LLMInvocationError, match="circuit open"):
        router.infer("API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA)

    assert provider.calls == 0


def test_consent_revoke_blocks__api_call_even__with_exact_scope() -> None:
    scope = _scope()
    checkpoint = ExternalScopeCheckpoint(scope=scope)
    provider = _Provider()
    with pytest.raises(LLMInvocationError) as captured:
        _router(checkpoint=checkpoint, api=provider, consent=False).infer(
            "API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA
        )
    assert captured.value.code is LLMErrorCode.CONSENT_REQUIRED
    assert provider.calls == 0


def test_scope_is__rechecked_before_api__schema_repair_call() -> None:
    scope = _scope()
    checkpoint = ExternalScopeCheckpoint(scope=scope)
    provider = _Provider(checkpoint_to_stale=checkpoint)
    repairer = _Repairer()
    with pytest.raises(LLMInvocationError):
        _router(checkpoint=checkpoint, api=provider, repairer=repairer).infer(
            "API_LLM", PROMPT, {"user_request": "hello"}, SCHEMA
        )
    assert provider.calls == 1
    assert repairer.calls == 0


def test_auto_fallback_does__not_call_api__without_published_scope() -> None:
    checkpoint = ExternalScopeCheckpoint()
    api = _Provider()
    local = _Provider(
        runtime=ActualRuntime.LOCAL_GPU,
        failure=LLMInvocationError(LLMErrorCode.GPU_OOM, "oom"),
    )
    with pytest.raises(LLMInvocationError):
        _router(checkpoint=checkpoint, api=api, local=local).infer(
            "AUTO", PROMPT, {"user_request": "hello"}, SCHEMA
        )
    assert local.calls == 1
    assert api.calls == 0
