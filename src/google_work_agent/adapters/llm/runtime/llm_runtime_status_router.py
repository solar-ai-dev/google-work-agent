"""Provider-parameterized LLM runtime-status router."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from google_work_agent.adapters.llm.gemini.runtime_status import GeminiLlmRuntimeStatusAdapter
from google_work_agent.adapters.llm.gemini.structured_inference import GeminiConnectionService
from google_work_agent.adapters.llm.runtime.llm_credential_router import LlmCredentialRouter
from google_work_agent.adapters.llm.runtime.local_model_selection import (
    LocalModelSelectionResolver,
)
from google_work_agent.ports.llm.llm_runtime_status_port import (
    LlmProviderRuntimeStatus,
    LocalModelRuntimeOptionV1,
)
from google_work_agent.ports.llm.runtime_selection import LlmRuntimeSelectionV1
from google_work_agent.ports.llm.structured_inference_contracts import (
    ApprovedModelInfo,
    RuntimePolicy,
)
from google_work_agent.ports.system.hardware_probe_port import HardwareProbePort


@dataclass
class LlmRuntimeStatusRouter:
    runtime_selection: LlmRuntimeSelectionV1
    credential_service: LlmCredentialRouter
    api_connection_service: GeminiConnectionService
    hardware_probe: HardwareProbePort
    runtime_policy: RuntimePolicy
    api_provider_name: str
    local_model_selection: LocalModelSelectionResolver | None = None

    def get_status(self, provider: str) -> LlmProviderRuntimeStatus:
        if provider in {"ollama", "LOCAL_GPU"}:
            status = self._ollama_status()
            return _with_provider(status, provider)
        actual_provider = self.api_provider_name if provider == "API_LLM" else provider
        if actual_provider != self.api_provider_name:
            return _status(provider, False, "DISABLED", None, "PROVIDER_NOT_CONFIGURED")
        credential = self.credential_service.get_credential_status(actual_provider)
        if not credential.configured:
            availability: Literal["UNAVAILABLE", "DISABLED"] = (
                "UNAVAILABLE" if credential.validation_status == "UNAVAILABLE" else "DISABLED"
            )
            return _status(provider, False, availability, None, credential.validation_status)
        secret = self.credential_service.read_secret(actual_provider)
        status = GeminiLlmRuntimeStatusAdapter(
            provider=actual_provider,
            connection=self.api_connection_service,
        ).get_status(
            api_key=None if secret is None else secret.decode("utf-8"),
            timeout_seconds=self.runtime_policy.api_timeout_seconds,
        )
        return _with_provider(status, provider)

    def get_approved_model(self, model_id: str) -> ApprovedModelInfo | None:
        if self.local_model_selection is not None:
            return self.local_model_selection.get_approved_model(model_id)
        return self.runtime_selection.get_approved_model(model_id)

    def get_selected_model(self) -> ApprovedModelInfo | None:
        if self.local_model_selection is not None:
            return self.local_model_selection.get_selected_model()
        return self.runtime_selection.selected_model

    def get_model_for_prompt(self, prompt_id: str) -> ApprovedModelInfo | None:
        if self.local_model_selection is not None:
            return self.local_model_selection.get_model_for_prompt(prompt_id)
        return self.runtime_selection.selected_model

    def list_local_models(self) -> tuple[LocalModelRuntimeOptionV1, ...]:
        if self.local_model_selection is None:
            return ()
        return self.local_model_selection.list_options()

    def _ollama_status(self) -> LlmProviderRuntimeStatus:
        selection = self.runtime_selection
        selected_model = self.get_selected_model()
        if not selection.is_active or selected_model is None:
            return _status(
                "ollama",
                False,
                "DISABLED",
                None if selected_model is None else selected_model.model_id,
                (
                    "LOCAL_MODEL_NOT_SELECTED"
                    if selection.is_active
                    else selection.local_runtime_activation_status.value
                ),
            )
        hardware = self.hardware_probe.probe()
        return _status(
            "ollama",
            True,
            "READY" if hardware.local_runtime_eligible else "UNAVAILABLE",
            selected_model.model_id,
            None
            if hardware.local_runtime_eligible
            else next(iter(hardware.local_runtime_reason_codes), "LOCAL_UNAVAILABLE"),
        )


def _status(
    provider: str,
    configured: bool,
    availability: Literal["READY", "UNAVAILABLE", "DISABLED"],
    model_id: str | None,
    error_code: str | None,
) -> LlmProviderRuntimeStatus:
    return LlmProviderRuntimeStatus(
        schema_version=1,
        provider=provider,
        configured=configured,
        availability=availability,
        model_id=model_id,
        error_code=error_code,
    )


def _with_provider(status: LlmProviderRuntimeStatus, provider: str) -> LlmProviderRuntimeStatus:
    return LlmProviderRuntimeStatus(
        schema_version=1,
        provider=provider,
        configured=status.configured,
        availability=status.availability,
        model_id=status.model_id,
        error_code=status.error_code,
    )


__all__ = ["LlmRuntimeStatusRouter"]
