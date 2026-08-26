"""Runtime-mode boundary."""

from typing import Protocol


class RuntimeModePort(Protocol):
    def current_mode(self) -> str: ...
