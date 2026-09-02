"""Provider-parameterized LLM runtime-status router."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from google_work_agent.adapters.llm.gemini.runtime_status import GeminiLlmRuntimeStatusAdapter
from google_work_agent.adapters.llm.gemini.structured_inference import GeminiConnectionService
from google_work_agent.adapters.llm.runtime.llm_credential_router import LlmCredentialRouter
from google_work_agent.ports.llm.llm_runtime_status_port import LlmProviderRuntimeStatus
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
        selected = self.runtime_selection.selected_model
        return selected if selected is not None and selected.model_id == model_id else None

    def _ollama_status(self) -> LlmProviderRuntimeStatus:
        selection = self.runtime_selection
        if not selection.is_active or selection.selected_model is None:
            return _status(
                "ollama",
                False,
                "DISABLED",
                selection.selected_model_id,
                selection.local_runtime_activation_status.value,
            )
        hardware = self.hardware_probe.probe()
        return _status(
            "ollama",
            True,
            "READY" if hardware.local_runtime_eligible else "UNAVAILABLE",
            selection.selected_model_id,
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
