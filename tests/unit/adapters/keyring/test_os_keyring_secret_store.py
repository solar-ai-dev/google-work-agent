from types import SimpleNamespace

import pytest

from google_work_agent.adapters.keyring.os_keyring_secret_store import (
    OsKeyringSecretStoreAdapter,
    keyring_service_name,
)


def test_os_keyring_secret_store_round_trips_bytes_without_exposing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values: dict[tuple[str, str], str] = {}

    def delete_password(service: str, key: str) -> None:
        values.pop((service, key), None)

    fake = SimpleNamespace(
        get_keyring=lambda: SimpleNamespace(priority=1),
        set_password=lambda service, key, value: values.__setitem__((service, key), value),
        get_password=lambda service, key: values.get((service, key)),
        delete_password=delete_password,
    )
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake)
    store = OsKeyringSecretStoreAdapter(service_name="GoogleWorkAgent/development/llm-api-key")

    store.put("provider", b"secret-value")
    assert values == {("GoogleWorkAgent.development.llm-api-key", "provider"): "secret-value"}
    assert store.get("provider") == b"secret-value"
    store.delete("provider")
    assert store.get("provider") is None


def test_keyring_namespace_is_closed_by_environment_and_credential_type() -> None:
    assert (
        keyring_service_name(environment="PRODUCTION", credential_type="google-oauth")
        == "GoogleWorkAgent/production/google-oauth"
    )
    assert (
        keyring_service_name(environment="STAGING", credential_type="llm-api-key")
        == "GoogleWorkAgent/staging/llm-api-key"
    )
    with pytest.raises(ValueError, match="unsupported keyring environment"):
        keyring_service_name(environment="personal", credential_type="llm-api-key")


def test_keyring_unavailable_has_no_plaintext_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = SimpleNamespace(get_keyring=lambda: SimpleNamespace(priority=0))
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake)

    with pytest.raises(RuntimeError, match="backend is unavailable"):
        OsKeyringSecretStoreAdapter(service_name="GoogleWorkAgent/development/llm-api-key")
