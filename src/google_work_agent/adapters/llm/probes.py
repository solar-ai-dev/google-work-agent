"""Default hardware and Ollama probe adapters."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass

from google_work_agent.adapters.llm.ollama import OllamaTransport
from google_work_agent.ports import (
    ApprovedModelInfo,
    AvailabilityState,
    HardwareCapability,
    HardwareCapabilityStatus,
    OllamaRuntimeProbe,
    ProbeResult,
)


@dataclass(frozen=True, slots=True)
class DefaultHardwareProbe:
    """Conservative hardware probe that fails closed for local GPU mode."""

    gpu_present: bool = False
    gpu_vendor: str | None = None
    gpu_name: str | None = None
    gpu_memory_bytes: int | None = None
    capability_status: HardwareCapabilityStatus = HardwareCapabilityStatus.NOT_VALIDATED

    def probe(self) -> HardwareCapability:
        return HardwareCapability(
            cpu_arch=platform.machine() or "unknown",
            core_summary=str(os.cpu_count() or "unknown"),
            memory_bytes=None,
            gpu_present=self.gpu_present,
            gpu_vendor=self.gpu_vendor,
            gpu_name=self.gpu_name,
            gpu_memory_bytes=self.gpu_memory_bytes,
            capability_status=self.capability_status,
            safe_reason_codes=()
            if self.capability_status is HardwareCapabilityStatus.VALIDATED
            else ("LOCAL_HARDWARE_NOT_VALIDATED",),
        )


@dataclass(frozen=True, slots=True)
class LoopbackOllamaProbe(OllamaRuntimeProbe):
    transport: OllamaTransport
    timeout_seconds: int = 5

    def probe(
        self,
        *,
        endpoint: str | None,
        approved_model: ApprovedModelInfo | None,
    ) -> ProbeResult:
        if endpoint is None:
            return ProbeResult(
                availability=AvailabilityState.NOT_CONFIGURED,
                safe_error_code="OLLAMA_ENDPOINT_NOT_CONFIGURED",
            )
        return self.transport.probe(
            endpoint=endpoint,
            model_id=None if approved_model is None else approved_model.model_id,
            timeout_seconds=self.timeout_seconds,
        )
