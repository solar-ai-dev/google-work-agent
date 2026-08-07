"""In-memory secret store test double."""

from __future__ import annotations


class FakeKeyring:
    """In-memory keyring that never touches the OS keychain."""

    def __init__(self) -> None:
        self._secrets: dict[tuple[str, str], str] = {}
        self.access_log: list[tuple[str, str, str]] = []

    def __repr__(self) -> str:
        return "FakeKeyring(secrets=<redacted>)"

    def set_secret(self, *, service: str, account: str, secret: str) -> None:
        """Store a secret in memory."""

        self._secrets[(service, account)] = secret
        self.access_log.append(("set", service, account))

    def get_secret(self, *, service: str, account: str) -> str | None:
        """Return a secret value if present."""

        self.access_log.append(("get", service, account))
        return self._secrets.get((service, account))

    def delete_secret(self, *, service: str, account: str) -> bool:
        """Delete a secret value if present."""

        self.access_log.append(("delete", service, account))
        return self._secrets.pop((service, account), None) is not None
