"""Runtime status service for local and API-backed LLM modes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import cast

from google_work_agent.adapters.llm.api_provider import APIProviderConnectionService
from google_work_agent.adapters.llm.credentials import LLMCredentialService
from google_work_agent.adapters.runtime.settings import AppSettings
from google_work_agent.ports import (
    ApprovedModelInfo,
    AvailabilityState,
    HardwareProbe,
    OllamaRuntimeProbe,
    ProbeResult,
    RequestedRuntimeMode,
    RuntimePolicy,
)


@dataclass
class LLMRuntimeStatusService:
    build_profile: str
    credential_service: LLMCredentialService
    api_connection_service: APIProviderConnectionService
    hardware_probe: HardwareProbe
    ollama_probe: OllamaRuntimeProbe
    approved_models: dict[str, ApprovedModelInfo]
    runtime_policy: RuntimePolicy

    def get_approved_model(self, model_id: str) -> ApprovedModelInfo | None:
        return self.approved_models.get(model_id)

    def get_runtime_status(self, settings: AppSettings) -> dict[str, object]:
        requested_mode = RequestedRuntimeMode(settings.requested_runtime_mode)
        credential_state = self.credential_service.describe_state()
        api_probe = self.api_connection_service.probe(
            api_key=self.credential_service.read_secret(),
            timeout_seconds=self.runtime_policy.api_timeout_seconds,
        )
        hardware = self.hardware_probe.probe()
        approved_model = self.approved_models.get(settings.approved_model_id or "")
        if self.build_profile == "API_ONLY":
            ollama_probe = ProbeResult(availability=AvailabilityState.NOT_APPLICABLE)
        else:
            ollama_probe = self.ollama_probe.probe(
                endpoint=settings.ollama_endpoint,
                approved_model=approved_model,
            )
        available_modes = (
            ["API_LLM"] if self.build_profile == "API_ONLY" else ["API_LLM", "LOCAL_GPU", "AUTO"]
        )
        return {
            "build_profile": self.build_profile,
            "requested_mode": requested_mode.value,
            "available_modes": available_modes,
            "actual_runtime": None,
            "external_llm_consent": settings.external_llm_consent,
            "api_provider": {
                "credential_state": credential_state.value,
                "availability": api_probe.availability.value,
                "last_probe": api_probe.last_probe_at_ms,
                "safe_error_code": api_probe.safe_error_code,
            },
            "ollama": {
                "visible": self.build_profile == "LOCAL_CAPABLE",
                "availability": (
                    AvailabilityState.NOT_APPLICABLE.value
                    if self.build_profile == "API_ONLY"
                    else ollama_probe.availability.value
                ),
                "version": ollama_probe.metadata.get("version"),
                "endpoint_state": (
                    "NOT_APPLICABLE"
                    if self.build_profile == "API_ONLY"
                    else ("CONFIGURED" if settings.ollama_endpoint else "NOT_CONFIGURED")
                ),
                "approved_model_state": _approved_model_state(
                    build_profile=self.build_profile,
                    settings=settings,
                    approved_model=approved_model,
                    ollama_probe=ollama_probe,
                ),
                "hardware_capability": asdict(hardware),
                "last_probe": ollama_probe.last_probe_at_ms,
                "safe_error_code": (
                    None if self.build_profile == "API_ONLY" else ollama_probe.safe_error_code
                ),
            },
        }

    def summarize_top_level(self, settings: AppSettings) -> tuple[str, str, dict[str, object]]:
        summary = self.get_runtime_status(settings)
        api_provider = cast(dict[str, object], summary["api_provider"])
        ollama = cast(dict[str, object], summary["ollama"])
        api_availability = str(api_provider["availability"])
        ollama_availability = str(ollama["availability"])
        return api_availability, ollama_availability, summary


def _approved_model_state(
    *,
    build_profile: str,
    settings: AppSettings,
    approved_model: ApprovedModelInfo | None,
    ollama_probe: ProbeResult,
) -> str:
    if build_profile == "API_ONLY":
        return "NOT_APPLICABLE"
    if settings.approved_model_id is None:
        return "NOT_CONFIGURED"
    if approved_model is None:
        return "NOT_APPROVED"
    if ollama_probe.safe_error_code == "MODEL_NOT_FOUND":
        return "MODEL_NOT_FOUND"
    return "APPROVED"
