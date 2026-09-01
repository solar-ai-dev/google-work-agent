"""LLM provider runtime-status boundary."""

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class LlmProviderRuntimeStatus:
    schema_version: Literal[1]
    provider: str
    configured: bool
    availability: Literal["READY", "UNAVAILABLE", "DISABLED"]
    model_id: str | None
    error_code: str | None


class LlmRuntimeStatusPort(Protocol):
    def get_status(self, provider: str) -> LlmProviderRuntimeStatus: ...


__all__ = ["LlmProviderRuntimeStatus", "LlmRuntimeStatusPort"]
