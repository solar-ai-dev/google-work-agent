"""Deterministic identity generator test double."""

from __future__ import annotations


class DeterministicUUID:
    """Deterministic ID generator with optional pre-seeded queue."""

    def __init__(
        self,
        *,
        queued_ids: tuple[str, ...] = (),
        prefix: str = "id",
        start: int = 1,
        require_queued_ids: bool = False,
    ) -> None:
        if start < 1:
            raise ValueError("start must be at least 1")
        self._queued_ids = list(queued_ids)
        self._prefix = prefix
        self._counter = start
        self._require_queued_ids = require_queued_ids
        self._seen: set[str] = set()

    def next_id(self) -> str:
        """Return the next deterministic identifier."""

        if self._queued_ids:
            candidate = self._queued_ids.pop(0)
        elif self._require_queued_ids:
            raise RuntimeError("deterministic id queue is exhausted")
        else:
            candidate = f"{self._prefix}-{self._counter:04d}"
            self._counter += 1

        if candidate in self._seen:
            raise RuntimeError(f"duplicate deterministic id generated: {candidate}")
        self._seen.add(candidate)
        return candidate

    def new_uuid(self) -> str:
        """Implement the canonical UUIDPort surface for boundary tests."""

        return self.next_id()
