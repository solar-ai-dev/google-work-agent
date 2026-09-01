"""LLM credential boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)


@dataclass(frozen=True, slots=True)
class LlmCredentialStatus:
    schema_version: Literal[1]
    provider: str
    configured: bool
    storage_mode: Literal["KEYRING", "SESSION_ONLY"] | None
    validation_status: Literal["VALID", "INVALID", "UNAVAILABLE", "NOT_CONFIGURED"]


class LlmCredentialPort(Protocol):
    def store_credential(
        self,
        provider: str,
        secret: bytes,
        storage_mode: Literal["KEYRING", "SESSION_ONLY"],
        operation_ref: str,
    ) -> LlmCredentialStatus: ...

    def delete_credential(self, provider: str, operation_ref: str) -> LlmCredentialStatus: ...

    def get_credential_status(self, provider: str) -> LlmCredentialStatus: ...

    def reconcile_credential(
        self,
        operation_ref: str,
        provider: str,
        target_state: Literal["CONFIGURED", "NOT_CONFIGURED"],
        storage_mode: Literal["KEYRING", "SESSION_ONLY"] | None = None,
    ) -> OperationalReconcileResultV1: ...


__all__ = ["LlmCredentialPort", "LlmCredentialStatus"]
