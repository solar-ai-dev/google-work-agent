"""LLM API key storage with keyring and session-memory modes."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.ports import CredentialStorageMode, LLMCredentialState, SecretStore


class SessionMemorySecretStore:
    """Ephemeral in-process secret store used for session-only API keys."""

    def __init__(self) -> None:
        self._values: dict[tuple[str, str], str] = {}

    def set_secret(self, *, service: str, account: str, secret: str) -> None:
        self._values[(service, account)] = secret

    def get_secret(self, *, service: str, account: str) -> str | None:
        return self._values.get((service, account))

    def delete_secret(self, *, service: str, account: str) -> bool:
        return self._values.pop((service, account), None) is not None


@dataclass
class LLMCredentialService:
    """Store one provider API key without exposing the secret value."""

    provider_name: str
    environment: str
    keyring_store: SecretStore | None
    session_store: SessionMemorySecretStore

    def describe_state(self) -> LLMCredentialState:
        if self.session_store.get_secret(service=self._service_name(), account=self.provider_name):
            return LLMCredentialState.SESSION_MEMORY
        if self.keyring_store is None:
            return LLMCredentialState.UNAVAILABLE
        if self.keyring_store.get_secret(service=self._service_name(), account=self.provider_name):
            return LLMCredentialState.KEYRING
        return LLMCredentialState.NOT_CONFIGURED

    def store(self, *, api_key: str, mode: CredentialStorageMode) -> LLMCredentialState:
        normalized = api_key.strip()
        if not normalized:
            raise ValueError("API key must not be blank")
        if mode is CredentialStorageMode.KEYRING:
            if self.keyring_store is None:
                raise ValueError("OS keyring is unavailable")
            self.keyring_store.set_secret(
                service=self._service_name(),
                account=self.provider_name,
                secret=normalized,
            )
            self.session_store.delete_secret(
                service=self._service_name(),
                account=self.provider_name,
            )
            return LLMCredentialState.KEYRING
        self.session_store.set_secret(
            service=self._service_name(),
            account=self.provider_name,
            secret=normalized,
        )
        if self.keyring_store is not None:
            self.keyring_store.delete_secret(
                service=self._service_name(),
                account=self.provider_name,
            )
        return LLMCredentialState.SESSION_MEMORY

    def read_secret(self) -> str | None:
        memory_value = self.session_store.get_secret(
            service=self._service_name(),
            account=self.provider_name,
        )
        if memory_value is not None:
            return memory_value
        if self.keyring_store is None:
            return None
        return self.keyring_store.get_secret(
            service=self._service_name(),
            account=self.provider_name,
        )

    def delete(self) -> LLMCredentialState:
        deleted = self.session_store.delete_secret(
            service=self._service_name(),
            account=self.provider_name,
        )
        if self.keyring_store is not None:
            deleted = (
                self.keyring_store.delete_secret(
                    service=self._service_name(),
                    account=self.provider_name,
                )
                or deleted
            )
        if deleted:
            return LLMCredentialState.NOT_CONFIGURED
        return self.describe_state()

    def _service_name(self) -> str:
        return f"GoogleWorkAgent/{self.environment}/llm-api-key"
