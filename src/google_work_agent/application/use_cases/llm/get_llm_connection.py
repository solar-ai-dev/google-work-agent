"""Read LLM connection state through Application authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class GetLLMConnectionQuery:
    """Read-only LLM connection request."""


@dataclass(frozen=True, slots=True)
class GetLLMConnectionResult:
    """Non-secret LLM connection projection."""

    llm: object


class GetLLMConnectionHandler:
    """Own LLM connection-state lookup."""

    def __init__(self, *, service_factory: Callable[[], Any | None]) -> None:
        self._service_factory = service_factory

    def handle(self, query: GetLLMConnectionQuery) -> GetLLMConnectionResult:
        del query
        service = self._service_factory()
        if service is None:
            raise RuntimeError("LLM_CONNECTION_UNAVAILABLE")
        return GetLLMConnectionResult(llm=service())
