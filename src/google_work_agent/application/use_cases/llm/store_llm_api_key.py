"""Store an LLM API key without projecting secret material back to callers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from google_work_agent.ports import CredentialStorageMode


@dataclass(frozen=True, slots=True)
class StoreLLMApiKeyCommand:
    api_key: str
    storage_mode: str


@dataclass(frozen=True, slots=True)
class StoreLLMApiKeyResult:
    credential_state: str


class StoreLLMApiKeyHandler:
    """Own the credential-store operation; results contain state only."""

    def __init__(self, *, service_factory: Callable[[], Any | None]) -> None:
        self._service_factory = service_factory

    def handle(self, command: StoreLLMApiKeyCommand) -> StoreLLMApiKeyResult:
        service = self._service_factory()
        if service is None:
            raise RuntimeError("LLM_CREDENTIAL_UNAVAILABLE")
        result = service(
            api_key=command.api_key,
            storage_mode=CredentialStorageMode(command.storage_mode),
        )
        return StoreLLMApiKeyResult(credential_state=str(result["credential_state"]))
