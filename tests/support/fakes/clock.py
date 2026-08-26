"""Deterministic clock test double."""

from __future__ import annotations


class FakeClockPort:
    """Deterministic millisecond clock with explicit mutation only."""

    def __init__(self, initial_ms: int = 0) -> None:
        if initial_ms < 0:
            raise ValueError("initial_ms must be non-negative")
        self._now_ms = initial_ms

    def now_ms(self) -> int:
        """Return the current fake time in milliseconds."""

        return self._now_ms

    def advance_ms(self, delta_ms: int) -> int:
        """Advance the fake clock and return the new time."""

        if delta_ms < 0:
            raise ValueError("delta_ms must be non-negative")
        self._now_ms += delta_ms
        return self._now_ms

    def set_ms(self, value_ms: int) -> int:
        """Set the fake clock and return the new time."""

        if value_ms < 0:
            raise ValueError("value_ms must be non-negative")
        self._now_ms = value_ms
        return self._now_ms
