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
    operating_system: str
    architecture: str
    local_runtime_reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.cpu_logical_cores < 1 or self.ram_total_bytes <= 0:
            raise ValueError("invalid hardware profile")
        if not self.gpu_present and (
            self.gpu_name is not None or self.vram_total_bytes is not None
        ):
            raise ValueError("GPU metadata requires an observed GPU")
        if self.local_runtime_eligible and self.local_runtime_reason_codes:
            raise ValueError("eligible local runtime cannot contain failure reasons")


class HardwareProbePort(Protocol):
    def probe(self) -> HardwareProfileV1: ...


__all__ = ["HardwareProbePort", "HardwareProfileV1"]
