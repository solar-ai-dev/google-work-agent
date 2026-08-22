"""Probe the configured LLM runtime through the registered Application collaborator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class TestLLMConnectionCommand:
    """Explicit user-requested LLM connection probe."""


@dataclass(frozen=True, slots=True)
class TestLLMConnectionResult:
    llm: object


class TestLLMConnectionHandler:
    """Never constructs a provider client; it uses the configured LLM boundary."""

    def __init__(self, *, service_factory: Callable[[], Any | None]) -> None:
        self._service_factory = service_factory

    def handle(self, command: TestLLMConnectionCommand) -> TestLLMConnectionResult:
        del command
        service = self._service_factory()
        if service is None:
            raise RuntimeError("LLM_TEST_UNAVAILABLE")
        return TestLLMConnectionResult(llm=service())
