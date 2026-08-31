"""Coordinate bounded child shutdown and settle Launcher runtime artifacts."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from launcher.acquire_single_instance import SingleInstanceLease
from launcher.create_service_instance_id import ServiceInstanceIdentity
from launcher.serve_instance_control import InstanceControlServer
from launcher.start_service import StartedService


@dataclass(frozen=True, slots=True)
class ShutdownResult:
    clean: bool
    forced: bool
    exit_code: int | None
    safe_error_code: str | None


def shutdown_service(
    *,
    service: StartedService | None,
    control_server: InstanceControlServer | None,
    identity: ServiceInstanceIdentity | None,
    lease: SingleInstanceLease | None,
    marker_path: Path,
    timeout_seconds: float = 30.0,
    safe_error_code: str | None = None,
    now_ms: int | None = None,
) -> ShutdownResult:
    """Request graceful process shutdown, force only after timeout, then settle artifacts."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    forced = False
    exit_code: int | None = None
    if service is not None:
        try:
            service.request_graceful_shutdown()
            exit_code = service.wait(timeout=timeout_seconds)
        except (OSError, TimeoutError, subprocess.TimeoutExpired):
            forced = True
            try:
                service.force_terminate()
                exit_code = service.wait(timeout=5)
            except (OSError, TimeoutError, subprocess.TimeoutExpired):
                safe_error_code = safe_error_code or "SHUTDOWN_TIMEOUT"
    try:
        if control_server is not None:
            control_server.close()
    except OSError:
        safe_error_code = safe_error_code or "CONTROL_CHANNEL_CLOSE_FAILED"
    try:
        if identity is not None:
            identity.clear()
    except OSError:
        safe_error_code = safe_error_code or "SERVICE_METADATA_CLEANUP_FAILED"
    try:
        if lease is not None:
            lease.release()
    except OSError:
        safe_error_code = safe_error_code or "SINGLE_INSTANCE_RELEASE_FAILED"
    clean = service is not None and not forced and exit_code == 0 and safe_error_code is None
    result = ShutdownResult(
        clean=clean,
        forced=forced,
        exit_code=exit_code,
        safe_error_code=safe_error_code,
    )
    _write_marker(
        marker_path,
        service_instance_id=None if identity is None else identity.service_instance_id,
        result=result,
        completed_at_ms=now_ms if now_ms is not None else time.time_ns() // 1_000_000,
    )
    return result


def _write_marker(
    marker_path: Path,
    *,
    service_instance_id: str | None,
    result: ShutdownResult,
    completed_at_ms: int,
) -> None:
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    bounded_error_code = (
        result.safe_error_code
        if result.safe_error_code is None
        or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", result.safe_error_code)
        else "LAUNCHER_SHUTDOWN_FAILED"
    )
    payload = {
        "schema_version": 1,
        "service_instance_id": service_instance_id,
        "status": "CLEAN" if result.clean else "UNCLEAN",
        "completed_at_ms": completed_at_ms,
        "exit_code": result.exit_code,
        "forced": result.forced,
        "safe_error_code": bounded_error_code,
    }
    temporary = marker_path.with_name(".shutdown.marker.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, marker_path)
