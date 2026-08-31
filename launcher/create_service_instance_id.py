"""Create service identity and own its bounded runtime metadata artifact."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ServiceInstanceIdentity:
    service_instance_id: str
    metadata_path: Path
    launcher_pid: int
    service_pid: int | None
    host: str
    port: int
    control_endpoint: str
    started_at_ms: int

    def bind_service_pid(self, service_pid: int) -> ServiceInstanceIdentity:
        if service_pid <= 0:
            raise ValueError("service_pid must be positive")
        updated = replace(self, service_pid=service_pid)
        _write_metadata(updated)
        return updated

    def clear(self) -> None:
        if not self.metadata_path.is_file():
            return
        try:
            payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if payload.get("service_instance_id") == self.service_instance_id:
            self.metadata_path.unlink(missing_ok=True)


def create_service_instance_id(
    runtime_dir: Path,
    *,
    host: str,
    port: int,
    control_endpoint: str,
    now_ms: int | None = None,
) -> ServiceInstanceIdentity:
    """Create a random instance ID and materialize non-secret process metadata."""

    if host != "127.0.0.1" or not 1 <= port <= 65535:
        raise ValueError("service identity requires a valid loopback endpoint")
    if not control_endpoint.startswith(r"\\.\pipe\GoogleWorkAgent-") or len(control_endpoint) > 128:
        raise ValueError("service identity requires a valid control endpoint")
    identity = ServiceInstanceIdentity(
        service_instance_id=str(uuid.uuid4()),
        metadata_path=runtime_dir.resolve() / "service-instance.json",
        launcher_pid=os.getpid(),
        service_pid=None,
        host=host,
        port=port,
        control_endpoint=control_endpoint,
        started_at_ms=now_ms if now_ms is not None else time.time_ns() // 1_000_000,
    )
    _write_metadata(identity)
    return identity


def _write_metadata(identity: ServiceInstanceIdentity) -> None:
    payload = {
        "schema_version": 1,
        "service_instance_id": identity.service_instance_id,
        "launcher_pid": identity.launcher_pid,
        "service_pid": identity.service_pid,
        "host": identity.host,
        "port": identity.port,
        "control_endpoint": identity.control_endpoint,
        "started_at_ms": identity.started_at_ms,
    }
    identity.metadata_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = identity.metadata_path.with_name(".service-instance.json.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, identity.metadata_path)
