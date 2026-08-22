"""Project the current Google account through Application authority."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class GetGoogleAccountQuery:
    """Read-only current-account request."""


@dataclass(frozen=True, slots=True)
class GetGoogleAccountResult:
    """Session-safe identity projection."""

    account: dict[str, object] | None


class GetGoogleAccountHandler:
    """Own identity projection independently of the HTTP representation."""

    def __init__(self, *, query_service_factory: Callable[[], Any]) -> None:
        self._query_service_factory = query_service_factory

    def handle(self, query: GetGoogleAccountQuery) -> GetGoogleAccountResult:
        del query
        account = self._query_service_factory().get_current_google_account()
        return GetGoogleAccountResult(account=None if account is None else asdict(account))
