"""Filesystem realization of the sanitized operational JSONL sink."""

from collections.abc import Callable
from pathlib import Path

from google_work_agent.ports.system.contracts.observability import (
    OperationalLogRecord,
    OperationalLogSink,
    sanitize_persistent_event_json,
)

OPERATIONAL_LOG_RETENTION_MS = 14 * 24 * 60 * 60 * 1000
MAX_LOG_FILE_BYTES = 10 * 1024 * 1024
MAX_LOG_DIR_BYTES = 200 * 1024 * 1024


class SanitizedJsonlLogSink(OperationalLogSink):
    """UTF-8 JSONL sink with scrubbing, rotation, retention, and size caps."""

    def __init__(
        self,
        *,
        directory: Path,
        filename_prefix: str,
        now_ms: Callable[[], int],
    ) -> None:
        self._directory = directory
        self._filename_prefix = filename_prefix
        self._now_ms = now_ms

    def append(self, record: OperationalLogRecord) -> None:
        event_json = sanitize_persistent_event_json(record.event_json)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._cleanup_expired_files()
        path = self._select_target_file()
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(event_json)
            handle.write("\n")
        self._enforce_directory_cap()

    def _select_target_file(self) -> Path:
        current = self._directory / f"{self._filename_prefix}.jsonl"
        if current.exists() and current.stat().st_size >= MAX_LOG_FILE_BYTES:
            rotated = self._directory / f"{self._filename_prefix}-{self._now_ms()}.jsonl"
            current.replace(rotated)
        return current

    def _cleanup_expired_files(self) -> None:
        cutoff_ms = self._now_ms() - OPERATIONAL_LOG_RETENTION_MS
        for path in self._directory.glob(f"{self._filename_prefix}*.jsonl"):
            if int(path.stat().st_mtime * 1000) < cutoff_ms:
                path.unlink(missing_ok=True)

    def _enforce_directory_cap(self) -> None:
        files = sorted(
            self._directory.glob(f"{self._filename_prefix}*.jsonl"),
            key=lambda item: item.stat().st_mtime,
        )
        total_bytes = sum(path.stat().st_size for path in files)
        while files and total_bytes > MAX_LOG_DIR_BYTES:
            path = files.pop(0)
            total_bytes -= path.stat().st_size
            path.unlink(missing_ok=True)


__all__ = ["SanitizedJsonlLogSink"]
