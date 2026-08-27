"""Provider-parameterized LLM runtime-status router."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from google_work_agent.adapters.llm.gemini.runtime_status import GeminiLlmRuntimeStatusAdapter
from google_work_agent.adapters.llm.gemini.structured_inference import GeminiConnectionService
from google_work_agent.adapters.llm.ollama.runtime_status import OllamaLlmRuntimeStatusAdapter
from google_work_agent.adapters.llm.runtime.llm_credential_router import LlmCredentialRouter
from google_work_agent.ports import (
    ApprovedModelInfo,
    AppSettings,
    OllamaRuntimeProbe,
    RuntimePolicy,
)
from google_work_agent.ports.llm.llm_runtime_status_port import LlmRuntimeStatusV1


@dataclass
class LlmRuntimeStatusRouter:
    build_profile: str
    settings_service: Callable[[], AppSettings]
    credential_service: LlmCredentialRouter
    api_connection_service: GeminiConnectionService
    ollama_probe: OllamaRuntimeProbe
    approved_models: dict[str, ApprovedModelInfo]
    runtime_policy: RuntimePolicy
    api_provider_name: str

    def get_status(self, provider: str) -> LlmRuntimeStatusV1:
        settings = self.settings_service()
        if provider == "ollama":
            return self._ollama_status(settings)
        if provider != self.api_provider_name:
            return _status(provider, False, "DISABLED", None, "PROVIDER_NOT_CONFIGURED")
        credential = self.credential_service.get_credential_status(provider)
        if not credential.configured:
            availability: Literal["UNAVAILABLE", "DISABLED"] = (
                "UNAVAILABLE" if credential.validation_status == "UNAVAILABLE" else "DISABLED"
            )
            return _status(provider, False, availability, None, credential.validation_status)
        secret = self.credential_service.read_secret(provider)
        return GeminiLlmRuntimeStatusAdapter(
            provider=provider,
            connection=self.api_connection_service,
        ).get_status(
            api_key=None if secret is None else secret.decode("utf-8"),
            timeout_seconds=self.runtime_policy.api_timeout_seconds,
        )

    def get_approved_model(self, model_id: str) -> ApprovedModelInfo | None:
        return self.approved_models.get(model_id)

    def _ollama_status(self, settings: AppSettings) -> LlmRuntimeStatusV1:
        if self.build_profile == "API_ONLY":
            return _status("ollama", False, "DISABLED", None, None)
        model = self.approved_models.get(settings.approved_model_id or "")
        if settings.ollama_endpoint is None or model is None:
            return _status(
                "ollama",
                False,
                "DISABLED",
                settings.approved_model_id,
                "LOCAL_RUNTIME_NOT_CONFIGURED",
            )
        return OllamaLlmRuntimeStatusAdapter(self.ollama_probe).get_status(
            endpoint=settings.ollama_endpoint,
            model=model,
        )


def _status(
    provider: str,
    configured: bool,
    availability: Literal["READY", "UNAVAILABLE", "DISABLED"],
    model_id: str | None,
    error_code: str | None,
) -> LlmRuntimeStatusV1:
    return LlmRuntimeStatusV1(
        schema_version=1,
        provider=provider,
        configured=configured,
        availability=availability,
        model_id=model_id,
        error_code=error_code,
    )


__all__ = ["LlmRuntimeStatusRouter"]
