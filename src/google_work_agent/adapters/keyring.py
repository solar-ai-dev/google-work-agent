"""OS keyring adapter."""

from __future__ import annotations

from google_work_agent.ports import SecretStore


class OSKeyringSecretStore(SecretStore):
    """Secret store backed by the host OS keyring."""

    def __init__(self) -> None:
        try:
            import keyring
        except ImportError as error:  # pragma: no cover - exercised by availability tests
            raise RuntimeError("keyring dependency is unavailable") from error
        self._keyring = keyring

    def set_secret(self, *, service: str, account: str, secret: str) -> None:
        self._keyring.set_password(service, account, secret)

    def get_secret(self, *, service: str, account: str) -> str | None:
        value = self._keyring.get_password(service, account)
        if value is None:
            return None
        return str(value)

    def delete_secret(self, *, service: str, account: str) -> bool:
        try:
            self._keyring.delete_password(service, account)
        except Exception:
            return False
        return True
