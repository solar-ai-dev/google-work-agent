"""System browser launcher boundary."""

from typing import Protocol


class BrowserLauncherPort(Protocol):
    def open(self, url: str) -> None: ...
