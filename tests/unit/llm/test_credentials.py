from tests.support.fakes import FakeKeyring

from google_work_agent.adapters.llm import (
    CredentialStorageMode,
    LLMCredentialService,
    SessionMemorySecretStore,
)
from google_work_agent.ports import LLMCredentialState


def test_keyring_storage_round_trip() -> None:
    service = LLMCredentialService(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=FakeKeyring(),
        session_store=SessionMemorySecretStore(),
    )

    stored = service.store(api_key="secret-key", mode=CredentialStorageMode.KEYRING)

    assert stored is LLMCredentialState.KEYRING
    assert service.describe_state() is LLMCredentialState.KEYRING
    assert service.read_secret() == "secret-key"


def test_session_memory_storage_does_not_require_keyring() -> None:
    service = LLMCredentialService(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=None,
        session_store=SessionMemorySecretStore(),
    )

    stored = service.store(api_key="memory-only", mode=CredentialStorageMode.SESSION_MEMORY)

    assert stored is LLMCredentialState.SESSION_MEMORY
    assert service.describe_state() is LLMCredentialState.SESSION_MEMORY
    assert service.read_secret() == "memory-only"


def test_delete_removes_current_provider_key_only() -> None:
    keyring = FakeKeyring()
    keyring.set_secret(
        service="GoogleWorkAgent/DEVELOPMENT/llm-api-key",
        account="other",
        secret="other-key",
    )
    service = LLMCredentialService(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=keyring,
        session_store=SessionMemorySecretStore(),
    )
    service.store(api_key="secret-key", mode=CredentialStorageMode.KEYRING)

    state = service.delete()

    assert state is LLMCredentialState.NOT_CONFIGURED
    assert (
        keyring.get_secret(
            service="GoogleWorkAgent/DEVELOPMENT/llm-api-key",
            account="other",
        )
        == "other-key"
    )
