"""Deterministic LLM runtime routing policy."""

from __future__ import annotations

from google_work_agent.adapters.runtime.build_manifest import BuildProfile
from google_work_agent.ports import (
    ActualRuntime,
    AvailabilityState,
    HardwareCapabilityStatus,
    LLMCredentialState,
    LLMRuntimeRouter,
    RequestedRuntimeMode,
    RouteDecision,
    RouteDecisionInput,
)


class DeterministicLLMRuntimeRouter(LLMRuntimeRouter):
    """Pure routing rules for API and local inference selection."""

    def decide(self, request: RouteDecisionInput) -> RouteDecision:
        profile = BuildProfile(request.build_profile)
        if profile is BuildProfile.API_ONLY:
            if request.requested_mode is not RequestedRuntimeMode.API_LLM:
                return RouteDecision(
                    primary_runtime=ActualRuntime.API_LLM,
                    fallback_allowed=False,
                    fallback_target=None,
                    safe_reason_code="API_ONLY_MODE_BLOCKED",
                )
            if not request.external_llm_consent:
                return RouteDecision(
                    primary_runtime=ActualRuntime.API_LLM,
                    fallback_allowed=False,
                    fallback_target=None,
                    safe_reason_code="CONSENT_REQUIRED",
                )
            return RouteDecision(
                primary_runtime=ActualRuntime.API_LLM,
                fallback_allowed=False,
                fallback_target=None,
                safe_reason_code=None,
            )

        if request.requested_mode is RequestedRuntimeMode.API_LLM:
            if not request.external_llm_consent:
                return RouteDecision(
                    primary_runtime=ActualRuntime.API_LLM,
                    fallback_allowed=False,
                    fallback_target=None,
                    safe_reason_code="CONSENT_REQUIRED",
                )
            return RouteDecision(
                primary_runtime=ActualRuntime.API_LLM,
                fallback_allowed=False,
                fallback_target=None,
                safe_reason_code=None,
            )

        if request.requested_mode is RequestedRuntimeMode.LOCAL_GPU:
            return RouteDecision(
                primary_runtime=ActualRuntime.LOCAL_GPU,
                fallback_allowed=False,
                fallback_target=None,
                safe_reason_code=_local_runtime_reason(request),
            )

        fallback_allowed = (
            request.external_llm_consent
            and request.api_credential_state
            in {
                LLMCredentialState.KEYRING,
                LLMCredentialState.SESSION_MEMORY,
            }
            and request.api_probe.availability
            in {AvailabilityState.AVAILABLE, AvailabilityState.UNKNOWN}
        )
        return RouteDecision(
            primary_runtime=ActualRuntime.LOCAL_GPU,
            fallback_allowed=fallback_allowed,
            fallback_target=ActualRuntime.API_LLM if fallback_allowed else None,
            safe_reason_code=_local_runtime_reason(request),
        )


def _local_runtime_reason(request: RouteDecisionInput) -> str | None:
    if request.hardware_capability.capability_status in {
        HardwareCapabilityStatus.UNKNOWN,
        HardwareCapabilityStatus.NOT_VALIDATED,
    }:
        return "LOCAL_HARDWARE_NOT_VALIDATED"
    if request.hardware_capability.capability_status is HardwareCapabilityStatus.INSUFFICIENT:
        return "LOCAL_HARDWARE_INSUFFICIENT"
    if request.approved_model is None:
        return "APPROVED_MODEL_UNAVAILABLE"
    if request.ollama_probe.safe_error_code is not None:
        return request.ollama_probe.safe_error_code
    if request.ollama_probe.availability is not AvailabilityState.AVAILABLE:
        return "OLLAMA_UNAVAILABLE"
    return None
