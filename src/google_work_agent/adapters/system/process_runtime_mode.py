"""Process configuration runtime-mode adapter."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProcessRuntimeModeAdapter:
    mode: str

    def current_mode(self) -> str:
        return self.mode
