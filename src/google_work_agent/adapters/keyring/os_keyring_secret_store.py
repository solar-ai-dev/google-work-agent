"""OS keyring adapter."""

from __future__ import annotations

from google_work_agent.ports.keyring.secret_store_port import SecretStorePort


class OsKeyringSecretStoreAdapter(SecretStorePort):
    """Secret store backed by the host OS keyring."""

    def __init__(self, *, service_name: str = "GoogleWorkAgent") -> None:
        if not service_name.strip():
            raise ValueError("keyring service_name is required")
        try:
            import keyring
        except ImportError as error:  # pragma: no cover - exercised by availability tests
            raise RuntimeError("keyring dependency is unavailable") from error
        self._keyring = keyring
        # Windows Credential Manager cannot round-trip '/' through python-keyring's
        # target-name lookup. Preserve the canonical logical namespace through a
        # deterministic backend-safe encoding.
        self._backend_service_name = service_name.replace("/", ".")
        try:
            backend = keyring.get_keyring()
            priority = float(backend.priority)
        except Exception as error:
            raise RuntimeError("OS keyring backend is unavailable") from error
        if priority <= 0:
            raise RuntimeError("OS keyring backend is unavailable")

    def put(self, key: str, secret_bytes: bytes) -> None:
        try:
            self._keyring.set_password(
                self._backend_service_name,
                key,
                secret_bytes.decode("utf-8"),
            )
        except Exception as error:
            raise RuntimeError("OS keyring write failed") from error

    def get(self, key: str) -> bytes | None:
        try:
            value = self._keyring.get_password(self._backend_service_name, key)
        except Exception as error:
            raise RuntimeError("OS keyring read failed") from error
        if value is None:
            return None
        return str(value).encode("utf-8")

    def delete(self, key: str) -> None:
        try:
            if self._keyring.get_password(self._backend_service_name, key) is None:
                return
            self._keyring.delete_password(self._backend_service_name, key)
        except Exception as error:
            raise RuntimeError("OS keyring delete failed") from error


def keyring_service_name(*, environment: str, credential_type: str) -> str:
    normalized_environment = environment.strip().lower()
    normalized_type = credential_type.strip().lower()
    if normalized_environment not in {"development", "staging", "production"}:
        raise ValueError("unsupported keyring environment")
    if normalized_type not in {"google-oauth", "llm-api-key"}:
        raise ValueError("unsupported keyring credential type")
    return f"GoogleWorkAgent/{normalized_environment}/{normalized_type}"


__all__ = ["OsKeyringSecretStoreAdapter", "keyring_service_name"]
