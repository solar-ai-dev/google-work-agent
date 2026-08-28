from types import SimpleNamespace

from google_work_agent.adapters.keyring.os_keyring_secret_store import (
    OsKeyringSecretStoreAdapter,
)


def test_os_keyring_secret_store_round_trips_bytes_without_exposing_secret(monkeypatch) -> None:
    values: dict[tuple[str, str], str] = {}

    def delete_password(service: str, key: str) -> None:
        values.pop((service, key), None)

    fake = SimpleNamespace(
        set_password=lambda service, key, value: values.__setitem__((service, key), value),
        get_password=lambda service, key: values.get((service, key)),
        delete_password=delete_password,
    )
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake)
    store = OsKeyringSecretStoreAdapter()

    store.put("provider", b"secret-value")
    assert store.get("provider") == b"secret-value"
    store.delete("provider")
    assert store.get("provider") is None
