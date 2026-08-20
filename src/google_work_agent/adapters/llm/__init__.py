"""LLM runtime adapters and fake-first routing helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from google_work_agent.adapters.llm.api_provider import (
    APIProviderConnectionService,
    APIProviderTransport,
    ApiStructuredLLMProvider as _ApiStructuredLLMProvider,
)
from google_work_agent.adapters.llm.credentials import (
    CredentialStorageMode,
    LLMCredentialService,
    SessionMemorySecretStore,
)
from google_work_agent.adapters.llm.gemini import (
    DEFAULT_GEMINI_BASE_URL,
    DEFAULT_GEMINI_MODEL_ID,
    GeminiHTTPClient,
)
from google_work_agent.adapters.llm.ollama import (
    OllamaHTTPClient,
    OllamaStructuredLLMProvider as _OllamaStructuredLLMProvider,
    OllamaTransport,
)
from google_work_agent.adapters.llm.probes import (
    DefaultHardwareProbe,
    LoopbackOllamaProbe,
)
from google_work_agent.adapters.llm.prompt_input_guard import PromptInputGuardedProvider
from google_work_agent.adapters.llm.router import DeterministicLLMRuntimeRouter
from google_work_agent.adapters.llm.schema import validate_output_schema
from google_work_agent.adapters.llm.status import LLMRuntimeStatusService
from google_work_agent.application.workflows.prompt_input_contract import (
    PromptRuntimeInputContractValidator,
)
from google_work_agent.application.workflows.prompt_registry import default_prompt_manifest_path
from google_work_agent.ports import ActualRuntime, PromptReference


def _no_instruction_text(prompt_ref: PromptReference) -> str:
    del prompt_ref
    return ""


class ApiStructuredLLMProvider(PromptInputGuardedProvider):
    """Production API provider with mandatory Product Prompt input validation."""

    __slots__ = ()

    def __init__(
        self,
        *,
        provider_name: str,
        transport: APIProviderTransport,
        model: str,
        runtime: ActualRuntime = ActualRuntime.API_LLM,
        resolve_instruction_text: Callable[[PromptReference], str] = _no_instruction_text,
        prompt_manifest_path: Path | None = None,
    ) -> None:
        manifest_path = prompt_manifest_path or default_prompt_manifest_path()
        super().__init__(
            delegate=_ApiStructuredLLMProvider(
                provider_name=provider_name,
                transport=transport,
                model=model,
                runtime=runtime,
                resolve_instruction_text=resolve_instruction_text,
            ),
            validator=PromptRuntimeInputContractValidator(manifest_path=manifest_path),
        )


class OllamaStructuredLLMProvider(PromptInputGuardedProvider):
    """Production Ollama provider with mandatory Product Prompt input validation."""

    __slots__ = ()

    def __init__(
        self,
        *,
        provider_name: str,
        transport: OllamaTransport,
        endpoint: str,
        model_id: str,
        runtime: ActualRuntime = ActualRuntime.LOCAL_GPU,
        resolve_instruction_text: Callable[[PromptReference], str] = _no_instruction_text,
        prompt_manifest_path: Path | None = None,
    ) -> None:
        manifest_path = prompt_manifest_path or default_prompt_manifest_path()
        super().__init__(
            delegate=_OllamaStructuredLLMProvider(
                provider_name=provider_name,
                transport=transport,
                endpoint=endpoint,
                model_id=model_id,
                runtime=runtime,
                resolve_instruction_text=resolve_instruction_text,
            ),
            validator=PromptRuntimeInputContractValidator(manifest_path=manifest_path),
        )


__all__ = [
    "APIProviderConnectionService",
    "APIProviderTransport",
    "ApiStructuredLLMProvider",
    "CredentialStorageMode",
    "DEFAULT_GEMINI_BASE_URL",
    "DEFAULT_GEMINI_MODEL_ID",
    "DefaultHardwareProbe",
    "DeterministicLLMRuntimeRouter",
    "GeminiHTTPClient",
    "LLMCredentialService",
    "LLMRuntimeStatusService",
    "LoopbackOllamaProbe",
    "OllamaHTTPClient",
    "OllamaStructuredLLMProvider",
    "OllamaTransport",
    "PromptInputGuardedProvider",
    "SessionMemorySecretStore",
    "validate_output_schema",
]
