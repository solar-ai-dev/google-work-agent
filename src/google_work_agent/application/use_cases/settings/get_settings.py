"""Read user settings through Application authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class GetSettingsQuery:
    """Read-only settings request."""


@dataclass(frozen=True, slots=True)
class GetSettingsResult:
    settings: dict[str, object]


class GetSettingsHandler:
    def __init__(self, *, service_factory: Callable[[], Any | None]) -> None:
        self._service_factory = service_factory

    def handle(self, query: GetSettingsQuery) -> GetSettingsResult:
        del query
        service = self._service_factory()
        if service is None:
            raise RuntimeError("SETTINGS_UNAVAILABLE")
        return GetSettingsResult(settings=asdict(service()))
