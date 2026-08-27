"""Read-only projection of the receipt-backed durable cancel fact."""

from typing import Protocol


class CancelIntentReader(Protocol):
    def has_durable_intent(self, run_id: str) -> bool: ...
