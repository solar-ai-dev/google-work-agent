"""Identity generation port definitions."""

from typing import Protocol


class UUIDPort(Protocol):
    """Generate deterministic or production identifiers."""

    def new_uuid(self) -> str:
        """Return the next generated identifier."""
