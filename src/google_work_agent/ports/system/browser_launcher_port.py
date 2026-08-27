"""System browser launcher boundary."""

from typing import Protocol


class BrowserLauncherPort(Protocol):
    def open_url(self, url: str) -> None: ...
