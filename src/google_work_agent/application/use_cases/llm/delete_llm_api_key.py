"""Delete the configured LLM API key through Application authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class DeleteLLMApiKeyCommand:
    """Credential deletion command."""


@dataclass(frozen=True, slots=True)
class DeleteLLMApiKeyResult:
    credential_state: str


class DeleteLLMApiKeyHandler:
    def __init__(self, *, service_factory: Callable[[], Any | None]) -> None:
        self._service_factory = service_factory

    def handle(self, command: DeleteLLMApiKeyCommand) -> DeleteLLMApiKeyResult:
        del command
        service = self._service_factory()
        if service is None:
            raise RuntimeError("LLM_CREDENTIAL_UNAVAILABLE")
        result = service()
        return DeleteLLMApiKeyResult(credential_state=str(result["credential_state"]))
