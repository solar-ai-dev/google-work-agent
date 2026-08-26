"""Process-local component circuit-state boundary."""

from typing import Protocol


class ComponentCircuitStatePort(Protocol):
    def is_open(self, component: str) -> bool: ...
    def set_open(self, component: str, is_open: bool) -> None: ...
