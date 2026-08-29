"""Narrow persistence surface for the P0 connected Google account fact."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ConnectedAccount:
    account_id: str
    email: str
    display_name: str | None


class ConnectedAccountStore(Protocol):
    def get_current(self) -> ConnectedAccount | None: ...

    def ensure_connected(
        self, *, email: str, display_name: str | None, connected_at_ms: int
    ) -> ConnectedAccount: ...

    def disconnect(self, *, account_id: str, disconnected_at_ms: int) -> bool: ...
