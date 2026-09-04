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


@dataclass(frozen=True, slots=True)
class LocalModelRuntimeOptionV1:
    schema_version: Literal[1]
    model_id: str
    installed: bool
    approved: bool
    selected: bool


class LlmRuntimeStatusPort(Protocol):
    def get_status(self, provider: str) -> LlmProviderRuntimeStatus: ...

    def list_local_models(self) -> tuple[LocalModelRuntimeOptionV1, ...]: ...


__all__ = [
    "LlmProviderRuntimeStatus",
    "LlmRuntimeStatusPort",
    "LocalModelRuntimeOptionV1",
]
