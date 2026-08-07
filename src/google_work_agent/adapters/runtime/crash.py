"""Crash and shutdown marker handling."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CrashMarker:
    service_instance_id: str
    process_id: int
    process_start_time: int
    release_version: str
    started_at_ms: int
    shutdown_phase: str | None = None
    safe_error_code: str | None = None


class CrashMarkerStore:
    def __init__(self, runtime_dir: Path) -> None:
        self._runtime_dir = runtime_dir

    def write_running(self, marker: CrashMarker) -> Path:
        return self._write("service-running.json", marker)

    def write_incomplete_shutdown(self, marker: CrashMarker) -> Path:
        return self._write("shutdown-incomplete.json", marker)

    def load(self, name: str) -> CrashMarker | None:
        path = self._runtime_dir / name
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return CrashMarker(
            service_instance_id=str(payload["service_instance_id"]),
            process_id=int(payload["process_id"]),
            process_start_time=int(payload["process_start_time"]),
            release_version=str(payload["release_version"]),
            started_at_ms=int(payload["started_at_ms"]),
            shutdown_phase=payload.get("shutdown_phase"),
            safe_error_code=payload.get("safe_error_code"),
        )

    def remove(self, name: str) -> None:
        path = self._runtime_dir / name
        if path.exists():
            os.remove(path)

    def _write(self, name: str, marker: CrashMarker) -> Path:
        self._runtime_dir.mkdir(parents=True, exist_ok=True)
        path = self._runtime_dir / name
        path.write_text(
            json.dumps(asdict(marker), ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        return path
