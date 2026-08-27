"""Bounded local diagnostics bundle adapter without secret access."""

import json
import os
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Literal

from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)
from google_work_agent.ports.system.diagnostics_port import DiagnosticBundleMetadataV1


class FilesystemDiagnosticsAdapter:
    def __init__(
        self,
        *,
        collect_snapshot: Callable[[], dict[str, object]],
        diagnostics_dir: Path,
        now_ms: Callable[[], int],
        max_bundle_bytes: int,
    ) -> None:
        self._collect_snapshot = collect_snapshot
        self._diagnostics_dir = diagnostics_dir
        self._now_ms = now_ms
        if max_bundle_bytes < 1:
            raise ValueError("max_bundle_bytes must be positive")
        self._max_bundle_bytes = max_bundle_bytes

    def create_bundle(
        self,
        scope: Literal["LAST_24H", "RUN"],
        run_id: str | None,
        operation_ref: str,
    ) -> DiagnosticBundleMetadataV1:
        if scope not in {"LAST_24H", "RUN"} or not operation_ref.strip():
            raise ValueError("valid scope and operation_ref are required")
        if scope == "RUN" and not run_id:
            raise ValueError("RUN diagnostics scope requires run_id")
        bundle_ref = sha256(operation_ref.encode("utf-8")).hexdigest()[:32]
        self._diagnostics_dir.mkdir(parents=True, exist_ok=True)
        path = self._path(bundle_ref)
        if not path.is_file():
            created_at_ms = self._now_ms()
            payload = {
                "schema_version": 1,
                "scope": scope,
                "run_id": run_id,
                "created_at_ms": created_at_ms,
                "operation_ref": operation_ref,
                "snapshot": _sanitize(self._collect_snapshot()),
            }
            data = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
            if len(data) > self._max_bundle_bytes:
                raise ValueError("diagnostic bundle exceeds configured size limit")
            _atomic_write(path, data)
        stored = json.loads(path.read_text(encoding="utf-8"))
        if (
            stored.get("operation_ref") != operation_ref
            or stored.get("scope") != scope
            or stored.get("run_id") != run_id
        ):
            raise ValueError("operation_ref already belongs to a different diagnostics request")
        return DiagnosticBundleMetadataV1(
            schema_version=1,
            bundle_ref=bundle_ref,
            scope=scope,
            created_at_ms=int(stored["created_at_ms"]),
            size_bytes=path.stat().st_size,
        )

    def reconcile_bundle(self, operation_ref: str) -> OperationalReconcileResultV1:
        bundle_ref = sha256(operation_ref.encode("utf-8")).hexdigest()[:32]
        path = self._path(bundle_ref)
        if not path.is_file():
            return OperationalReconcileResultV1("SAFE_TO_RETRY", None, None)
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return OperationalReconcileResultV1("UNCERTAIN", None, None)
        if (
            not isinstance(stored, dict)
            or stored.get("operation_ref") != operation_ref
            or path.stat().st_size > self._max_bundle_bytes
        ):
            return OperationalReconcileResultV1("UNCERTAIN", None, None)
        return OperationalReconcileResultV1(
            "COMPLETED", bundle_ref, {"bundle_ref": bundle_ref, "size_bytes": path.stat().st_size}
        )

    def _path(self, bundle_ref: str) -> Path:
        return self._diagnostics_dir / f"{bundle_ref}.json"


_SECRET_KEY_FRAGMENTS = (
    "access_token",
    "refresh_token",
    "api_key",
    "password",
    "secret",
    "authorization",
    "cookie",
    "claim_token",
)


def _sanitize(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if any(fragment in str(key).lower() for fragment in _SECRET_KEY_FRAGMENTS)
                else _sanitize(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _atomic_write(path: Path, data: bytes) -> None:
    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp_path, path)
