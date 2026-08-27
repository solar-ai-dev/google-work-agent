"""Conservative Windows hardware probe that fails closed for local GPU mode."""

from __future__ import annotations

import os
from dataclasses import dataclass

from google_work_agent.ports.system.hardware_probe_port import HardwareProfileV1


@dataclass(frozen=True, slots=True)
class WindowsHardwareProbeAdapter:
    ram_total_bytes: int = 1
    gpu_present: bool = False
    gpu_name: str | None = None
    vram_total_bytes: int | None = None
    ollama_available: bool = False
    ollama_version: str | None = None
    local_runtime_eligible: bool = False

    def probe(self) -> HardwareProfileV1:
        return HardwareProfileV1(
            schema_version=1,
            cpu_logical_cores=max(1, os.cpu_count() or 1),
            ram_total_bytes=max(1, self.ram_total_bytes),
            gpu_present=self.gpu_present,
            gpu_name=self.gpu_name,
            vram_total_bytes=self.vram_total_bytes,
            ollama_available=self.ollama_available,
            ollama_version=self.ollama_version,
            local_runtime_eligible=self.local_runtime_eligible,
        )
