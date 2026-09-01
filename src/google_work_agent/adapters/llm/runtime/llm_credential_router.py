"""LLM credential router and session-memory credential leaf."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from google_work_agent.adapters.llm.gemini.credential import GeminiLlmCredentialAdapter
from google_work_agent.ports.keyring.secret_store_port import SecretStorePort
from google_work_agent.ports.llm.llm_credential_port import LlmCredentialStatus
from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)


class SessionMemorySecretStore(SecretStorePort):
    def __init__(self) -> None:
        self._values: dict[str, bytes] = {}

    def put(self, key: str, secret_bytes: bytes) -> None:
        self._values[key] = bytes(secret_bytes)

    def get(self, key: str) -> bytes | None:
        return self._values.get(key)

    def delete(self, key: str) -> None:
        self._values.pop(key, None)


@dataclass
class LlmCredentialRouter:
    """Route provider credentials without exposing secret values in results."""

    environment: str
    keyring_store: SecretStorePort | None
    session_store: SessionMemorySecretStore
    provider_name: str | None = None
    _leaves: dict[str, GeminiLlmCredentialAdapter] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if self.provider_name is not None:
            self._leaves[self.provider_name] = GeminiLlmCredentialAdapter(
                provider=self.provider_name,
                environment=self.environment,
                keyring_store=self.keyring_store,
                session_store=self.session_store,
            )

    def store_credential(
        self,
        provider: str,
        secret: bytes,
        storage_mode: Literal["KEYRING", "SESSION_ONLY"],
        operation_ref: str,
    ) -> LlmCredentialStatus:
        return self._leaf(provider).store(secret, storage_mode, operation_ref)

    def delete_credential(self, provider: str, operation_ref: str) -> LlmCredentialStatus:
        return self._leaf(provider).delete(operation_ref)

    def get_credential_status(self, provider: str) -> LlmCredentialStatus:
        return self._leaf(provider).status()

    def reconcile_credential(
        self,
        operation_ref: str,
        provider: str,
        target_state: Literal["CONFIGURED", "NOT_CONFIGURED"],
        storage_mode: Literal["KEYRING", "SESSION_ONLY"] | None = None,
    ) -> OperationalReconcileResultV1:
        return self._leaf(provider).reconcile(
            operation_ref,
            target_state,
            storage_mode,
        )

    def read_secret(self, provider: str) -> bytes | None:
        """Router-private handoff used only by a provider inference leaf."""
        return self._leaf(provider).read_secret()

    def _leaf(self, provider: str) -> GeminiLlmCredentialAdapter:
        if not provider:
            raise ValueError("unknown LLM provider")
        leaf = self._leaves.get(provider)
        if leaf is None:
            if self.provider_name is not None:
                raise ValueError("unknown LLM provider")
            leaf = GeminiLlmCredentialAdapter(
                provider=provider,
                environment=self.environment,
                keyring_store=self.keyring_store,
                session_store=self.session_store,
            )
            self._leaves[provider] = leaf
        return leaf


__all__ = ["LlmCredentialRouter", "SessionMemorySecretStore"]
