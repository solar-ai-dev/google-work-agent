"""Hardware profile boundary."""

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class HardwareProfileV1:
    schema_version: Literal[1]
    cpu_logical_cores: int
    ram_total_bytes: int
    gpu_present: bool
    gpu_name: str | None
    vram_total_bytes: int | None
    ollama_available: bool
    ollama_version: str | None
    local_runtime_eligible: bool


class HardwareProbePort(Protocol):
    def probe(self) -> HardwareProfileV1: ...


__all__ = ["HardwareProbePort", "HardwareProfileV1"]
