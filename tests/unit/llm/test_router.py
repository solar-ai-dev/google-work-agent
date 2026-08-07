from tests.support.fakes import approved_model

from google_work_agent.adapters.llm.router import DeterministicLLMRuntimeRouter
from google_work_agent.ports import (
    ActualRuntime,
    AvailabilityState,
    HardwareCapability,
    HardwareCapabilityStatus,
    LLMCredentialState,
    ProbeResult,
    RequestedRuntimeMode,
    RouteDecisionInput,
)


def _hardware(status: HardwareCapabilityStatus) -> HardwareCapability:
    return HardwareCapability(
        cpu_arch="x86_64",
        core_summary="8",
        memory_bytes=16,
        gpu_present=status is HardwareCapabilityStatus.VALIDATED,
        gpu_vendor=None,
        gpu_name=None,
        gpu_memory_bytes=None,
        capability_status=status,
        safe_reason_codes=(),
    )


def test_api_only_forces_api_runtime() -> None:
    decision = DeterministicLLMRuntimeRouter().decide(
        RouteDecisionInput(
            build_profile="API_ONLY",
            requested_mode=RequestedRuntimeMode.API_LLM,
            external_llm_consent=True,
            api_credential_state=LLMCredentialState.KEYRING,
            api_probe=ProbeResult(availability=AvailabilityState.AVAILABLE),
            hardware_capability=_hardware(HardwareCapabilityStatus.NOT_APPLICABLE),
            ollama_probe=ProbeResult(availability=AvailabilityState.NOT_APPLICABLE),
            approved_model=None,
        )
    )
    assert decision.primary_runtime is ActualRuntime.API_LLM
    assert decision.fallback_allowed is False


def test_api_only_blocks_local_gpu_request() -> None:
    decision = DeterministicLLMRuntimeRouter().decide(
        RouteDecisionInput(
            build_profile="API_ONLY",
            requested_mode=RequestedRuntimeMode.LOCAL_GPU,
            external_llm_consent=True,
            api_credential_state=LLMCredentialState.KEYRING,
            api_probe=ProbeResult(availability=AvailabilityState.AVAILABLE),
            hardware_capability=_hardware(HardwareCapabilityStatus.NOT_APPLICABLE),
            ollama_probe=ProbeResult(availability=AvailabilityState.NOT_APPLICABLE),
            approved_model=None,
        )
    )
    assert decision.primary_runtime is ActualRuntime.API_LLM
    assert decision.safe_reason_code == "API_ONLY_MODE_BLOCKED"


def test_auto_allows_one_api_fallback_when_local_is_unavailable_and_consent_exists() -> None:
    decision = DeterministicLLMRuntimeRouter().decide(
        RouteDecisionInput(
            build_profile="LOCAL_CAPABLE",
            requested_mode=RequestedRuntimeMode.AUTO,
            external_llm_consent=True,
            api_credential_state=LLMCredentialState.KEYRING,
            api_probe=ProbeResult(availability=AvailabilityState.AVAILABLE),
            hardware_capability=_hardware(HardwareCapabilityStatus.VALIDATED),
            ollama_probe=ProbeResult(
                availability=AvailabilityState.UNAVAILABLE,
                safe_error_code="OLLAMA_UNAVAILABLE",
            ),
            approved_model=approved_model(),
        )
    )
    assert decision.primary_runtime is ActualRuntime.LOCAL_GPU
    assert decision.fallback_allowed is True
    assert decision.fallback_target is ActualRuntime.API_LLM


def test_local_gpu_never_allows_api_fallback() -> None:
    decision = DeterministicLLMRuntimeRouter().decide(
        RouteDecisionInput(
            build_profile="LOCAL_CAPABLE",
            requested_mode=RequestedRuntimeMode.LOCAL_GPU,
            external_llm_consent=True,
            api_credential_state=LLMCredentialState.KEYRING,
            api_probe=ProbeResult(availability=AvailabilityState.AVAILABLE),
            hardware_capability=_hardware(HardwareCapabilityStatus.INSUFFICIENT),
            ollama_probe=ProbeResult(availability=AvailabilityState.UNAVAILABLE),
            approved_model=approved_model(),
        )
    )
    assert decision.primary_runtime is ActualRuntime.LOCAL_GPU
    assert decision.fallback_allowed is False
    assert decision.safe_reason_code == "LOCAL_HARDWARE_INSUFFICIENT"
