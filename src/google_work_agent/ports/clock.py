"""Clock port definitions."""

from typing import Protocol


class Clock(Protocol):
    """Return the current UTC epoch time in milliseconds."""

    def now_ms(self) -> int:
        """Return the current UTC epoch time in milliseconds."""
