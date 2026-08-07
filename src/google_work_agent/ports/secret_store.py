"""Secret store port definitions."""

from typing import Protocol


class SecretStore(Protocol):
    """Store and retrieve secrets by service and account."""

    def set_secret(self, *, service: str, account: str, secret: str) -> None:
        """Store or replace a secret value."""

    def get_secret(self, *, service: str, account: str) -> str | None:
        """Return a secret value if present."""

    def delete_secret(self, *, service: str, account: str) -> bool:
        """Delete a secret value and return whether it existed."""
