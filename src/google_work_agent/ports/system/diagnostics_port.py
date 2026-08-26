"""Sanitized diagnostics bundle boundary."""

from typing import Protocol


class DiagnosticsPort(Protocol):
    def collect(self) -> dict[str, object]: ...
