"""Conservative Windows hardware probe that fails closed for local GPU mode."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass

from google_work_agent.ports import HardwareCapability, HardwareCapabilityStatus


@dataclass(frozen=True, slots=True)
class WindowsHardwareProbeAdapter:
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
