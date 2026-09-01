"""Gemini provider-private credential storage leaf."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Literal

from google_work_agent.ports.keyring.secret_store_port import SecretStorePort
from google_work_agent.ports.llm.llm_credential_port import LlmCredentialStatus
from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)


@dataclass
class GeminiLlmCredentialAdapter:
    provider: str
    environment: str
    keyring_store: SecretStorePort | None
    session_store: SecretStorePort
    _operations: dict[str, tuple[str, str | None, str | None]] = field(
        default_factory=dict, init=False
    )

    @property
    def _key(self) -> str:
        return f"{self.environment}/llm-api-key/{self.provider}"

    def store(
        self,
        secret: bytes,
        storage_mode: Literal["KEYRING", "SESSION_ONLY"],
        operation_ref: str,
    ) -> LlmCredentialStatus:
        normalized = secret.strip()
        if not normalized:
            raise ValueError("API key must not be blank")
        operation = ("CONFIGURED", storage_mode, sha256(normalized).hexdigest())
        if self._validate_operation(operation_ref, operation):
            return self.status()
        if storage_mode == "KEYRING":
            if self.keyring_store is None:
                return self._status(None, "UNAVAILABLE")
            self.keyring_store.put(self._key, normalized)
            self.session_store.delete(self._key)
        else:
            self.session_store.put(self._key, normalized)
            if self.keyring_store is not None:
                self.keyring_store.delete(self._key)
        self._operations[operation_ref] = operation
        return self._status(storage_mode, "VALID")

    def delete(self, operation_ref: str) -> LlmCredentialStatus:
        operation = ("NOT_CONFIGURED", None, None)
        if self._validate_operation(operation_ref, operation):
            return self.status()
        self.session_store.delete(self._key)
        if self.keyring_store is not None:
            self.keyring_store.delete(self._key)
        self._operations[operation_ref] = operation
        return self._status(None, "NOT_CONFIGURED")

    def status(self) -> LlmCredentialStatus:
        if self.session_store.get(self._key) is not None:
            return self._status("SESSION_ONLY", "VALID")
        if self.keyring_store is None:
            return self._status(None, "UNAVAILABLE")
        if self.keyring_store.get(self._key) is not None:
            return self._status("KEYRING", "VALID")
        return self._status(None, "NOT_CONFIGURED")

    def read_secret(self) -> bytes | None:
        return self.session_store.get(self._key) or (
            None if self.keyring_store is None else self.keyring_store.get(self._key)
        )

    def reconcile(
        self,
        operation_ref: str,
        target_state: Literal["CONFIGURED", "NOT_CONFIGURED"],
        storage_mode: Literal["KEYRING", "SESSION_ONLY"] | None,
    ) -> OperationalReconcileResultV1:
        status = self.status()
        operation = self._operations.get(operation_ref)
        completed = (
            operation is not None
            and operation[:2] == (target_state, storage_mode)
            and (status.configured if target_state == "CONFIGURED" else not status.configured)
        )
        return OperationalReconcileResultV1(
            status="COMPLETED" if completed else "SAFE_TO_RETRY",
            result_ref=operation_ref if completed else None,
            bounded_result={"provider": self.provider, "configured": status.configured},
        )

    def _validate_operation(
        self,
        operation_ref: str,
        requested: tuple[str, str | None, str | None],
    ) -> bool:
        if not operation_ref.strip():
            raise ValueError("operation_ref is required")
        existing = self._operations.get(operation_ref)
        if existing is not None and existing != requested:
            raise ValueError("operation_ref already belongs to a different credential mutation")
        return existing is not None

    def _status(
        self,
        storage_mode: Literal["KEYRING", "SESSION_ONLY"] | None,
        validation_status: Literal["VALID", "INVALID", "UNAVAILABLE", "NOT_CONFIGURED"],
    ) -> LlmCredentialStatus:
        return LlmCredentialStatus(
            schema_version=1,
            provider=self.provider,
            configured=validation_status == "VALID",
            storage_mode=storage_mode,
            validation_status=validation_status,
        )


__all__ = ["GeminiLlmCredentialAdapter"]
