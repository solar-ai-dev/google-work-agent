"""Local diagnostics adapter without provider or secret access."""

from collections.abc import Callable


class FilesystemDiagnosticsAdapter:
    def __init__(self, *, collect_snapshot: Callable[[], dict[str, object]]) -> None:
        self._collect_snapshot = collect_snapshot

    def collect(self) -> dict[str, object]:
        return dict(self._collect_snapshot())
