"""Identity generation port definitions."""

from typing import Protocol


class IdGenerator(Protocol):
    """Generate deterministic or production identifiers."""

    def next_id(self) -> str:
        """Return the next generated identifier."""
