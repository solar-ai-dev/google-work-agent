"""OS keyring adapter."""

from __future__ import annotations

from google_work_agent.ports import SecretStorePort


class OsKeyringSecretStoreAdapter(SecretStorePort):
    """Secret store backed by the host OS keyring."""

    def __init__(self) -> None:
        try:
            import keyring
        except ImportError as error:  # pragma: no cover - exercised by availability tests
            raise RuntimeError("keyring dependency is unavailable") from error
        self._keyring = keyring

    def put(self, key: str, secret_bytes: bytes) -> None:
        self._keyring.set_password(_SERVICE_NAME, key, secret_bytes.decode("utf-8"))

    def get(self, key: str) -> bytes | None:
        value = self._keyring.get_password(_SERVICE_NAME, key)
        if value is None:
            return None
        return str(value).encode("utf-8")

    def delete(self, key: str) -> None:
        try:
            self._keyring.delete_password(_SERVICE_NAME, key)
        except Exception:
            return


_SERVICE_NAME = "GoogleWorkAgent"
