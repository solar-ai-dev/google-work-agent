"""SQLite online backup and restore validation helpers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.ports import (
    BackupCreateResult,
    BackupManifestRecord,
    ClockPort,
    MaintenanceGate,
)
from google_work_agent.ports.system.backup_port import BackupMetadataV1, RestoreResultV1
from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)


class FilesystemBackupAdapter:
    def __init__(
        self,
        *,
        database_path: Path,
        backups_dir: Path,
        clock: ClockPort,
        maintenance_gate: MaintenanceGate,
        release_version: str,
        domain_contract_version: str,
        schema_version: str,
    ) -> None:
        self._database_path = database_path
        self._backups_dir = backups_dir
        self._clock = clock
        self._maintenance_gate = maintenance_gate
        self._release_version = release_version
        self._domain_contract_version = domain_contract_version
        self._schema_version = schema_version

    def create_backup(self, operation_ref: str) -> BackupMetadataV1:
        result = self._create_backup_record(operation_ref)
        return _metadata(result.backup)

    def _create_backup_record(self, operation_ref: str) -> BackupCreateResult:
        if not operation_ref.strip():
            raise ValueError("operation_ref is required")
        window = self._maintenance_gate.snapshot()
        if window.has_active_write or window.migration_running or window.restore_running:
            raise ValueError("maintenance window does not allow backup")
        self._backups_dir.mkdir(parents=True, exist_ok=True)
        backup_id = hashlib.sha256(operation_ref.encode("utf-8")).hexdigest()[:32]
        backup_path = self._backups_dir / f"{backup_id}.sqlite3"
        manifest_path = self._backups_dir / f"{backup_id}.manifest.json"
        if backup_path.is_file() and manifest_path.is_file():
            existing = _manifest_from_path(manifest_path)
            if _sha256_file(backup_path) != existing.backup_sha256:
                raise ValueError("existing operation backup failed integrity validation")
            return BackupCreateResult(
                backup=existing,
                database_path=backup_path,
                manifest_path=manifest_path,
            )
        if backup_path.exists() or manifest_path.exists():
            raise ValueError("incomplete existing operation backup requires reconciliation")
        temporary_backup_path = backup_path.with_name(f".{backup_path.name}.tmp")
        temporary_backup_path.unlink(missing_ok=True)
        source = connect_sqlite(self._database_path)
        try:
            destination = sqlite3.connect(str(temporary_backup_path))
            try:
                source.backup(destination)
                destination.execute("PRAGMA foreign_keys = ON;")
                quick_check_result = _pragma_single_value(destination, "PRAGMA quick_check;")
                foreign_key_rows = destination.execute("PRAGMA foreign_key_check;").fetchall()
                foreign_key_result = "ok" if not foreign_key_rows else "failed"
            finally:
                destination.close()
        finally:
            source.close()
        sha256 = _sha256_file(temporary_backup_path)
        record = BackupManifestRecord(
            backup_id=backup_id,
            created_at_ms=self._clock.now_ms(),
            release_version=self._release_version,
            database_schema_version=self._schema_version,
            domain_contract_version=self._domain_contract_version,
            source_db_identity=_sha256_file(self._database_path),
            backup_sha256=sha256,
            backup_size_bytes=temporary_backup_path.stat().st_size,
            quick_check_result=quick_check_result,
            foreign_key_check_result=foreign_key_result,
        )
        os.replace(temporary_backup_path, backup_path)
        _atomic_write(
            manifest_path,
            json.dumps(asdict(record), ensure_ascii=False, sort_keys=True, indent=2).encode(
                "utf-8"
            ),
        )
        self._apply_retention(now_ms=record.created_at_ms)
        return BackupCreateResult(
            backup=record,
            database_path=backup_path,
            manifest_path=manifest_path,
        )

    def list_backups(self) -> list[BackupMetadataV1]:
        return [_metadata(record) for record in self._list_records()]

    def _list_records(self) -> tuple[BackupManifestRecord, ...]:
        if not self._backups_dir.exists():
            return ()
        manifests = []
        for path in sorted(self._backups_dir.glob("*.manifest.json")):
            manifests.append(_manifest_from_path(path))
        manifests.sort(key=lambda item: item.created_at_ms, reverse=True)
        return tuple(manifests)

    def _apply_retention(self, *, now_ms: int) -> None:
        manifests = list(self._list_records())
        keep_cutoff = datetime.fromtimestamp(now_ms / 1000, tz=UTC) - timedelta(days=30)
        retained = manifests[:5]
        retained_ids = {item.backup_id for item in retained}
        for item in manifests[5:]:
            created_at = datetime.fromtimestamp(item.created_at_ms / 1000, tz=UTC)
            if created_at > keep_cutoff:
                retained_ids.add(item.backup_id)
        for item in manifests:
            if item.backup_id in retained_ids:
                continue
            for suffix in (".sqlite3", ".manifest.json"):
                candidate = self._backups_dir / f"{item.backup_id}{suffix}"
                if candidate.exists():
                    try:
                        os.remove(candidate)
                    except OSError:
                        continue

    def reconcile_backup(self, operation_ref: str) -> OperationalReconcileResultV1:
        if not operation_ref.strip():
            raise ValueError("operation_ref is required")
        backup_ref = hashlib.sha256(operation_ref.encode("utf-8")).hexdigest()[:32]
        backup_path = self._backups_dir / f"{backup_ref}.sqlite3"
        manifest_path = self._backups_dir / f"{backup_ref}.manifest.json"
        metadata = next(
            (item for item in self.list_backups() if item.backup_ref == backup_ref), None
        )
        if metadata is None:
            if backup_path.exists() or manifest_path.exists():
                return OperationalReconcileResultV1("UNCERTAIN", backup_ref, None)
            return OperationalReconcileResultV1("SAFE_TO_RETRY", None, None)
        try:
            manifest = _manifest_from_path(manifest_path)
            integrity_matches = (
                manifest.backup_id == backup_ref
                and backup_path.is_file()
                and _sha256_file(backup_path) == manifest.backup_sha256
                and backup_path.stat().st_size == manifest.backup_size_bytes
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            integrity_matches = False
        if not integrity_matches:
            return OperationalReconcileResultV1("UNCERTAIN", backup_ref, None)
        return OperationalReconcileResultV1("COMPLETED", backup_ref, {"backup_ref": backup_ref})

    def restore_backup(self, backup_ref: str, operation_ref: str) -> RestoreResultV1:
        if not operation_ref.strip():
            raise ValueError("operation_ref is required")
        marker = self._restore_marker(operation_ref)
        if marker.is_file():
            payload = json.loads(marker.read_text(encoding="utf-8"))
            if payload.get("backup_ref") != backup_ref:
                raise ValueError("operation_ref already belongs to a different restore")
            if payload.get("status") == "COMPLETED":
                return RestoreResultV1(1, backup_ref, "RESTORED", None)
        manifest_path = self._backups_dir / f"{backup_ref}.manifest.json"
        backup_path = self._backups_dir / f"{backup_ref}.sqlite3"
        if not manifest_path.is_file() or not backup_path.is_file():
            return RestoreResultV1(1, backup_ref, "REJECTED", "BACKUP_NOT_FOUND")
        manifest = _manifest_from_path(manifest_path)
        if _sha256_file(backup_path) != manifest.backup_sha256:
            return RestoreResultV1(1, backup_ref, "REJECTED", "BACKUP_HASH_MISMATCH")
        if manifest.database_schema_version != self._schema_version:
            return RestoreResultV1(1, backup_ref, "REJECTED", "BACKUP_SCHEMA_MISMATCH")
        window = self._maintenance_gate.snapshot()
        if window.has_active_write or window.migration_running or window.restore_running:
            return RestoreResultV1(1, backup_ref, "REJECTED", "RESTORE_WINDOW_UNAVAILABLE")
        connection = sqlite3.connect(str(backup_path))
        try:
            if _pragma_single_value(connection, "PRAGMA quick_check;") != "ok":
                return RestoreResultV1(1, backup_ref, "REJECTED", "BACKUP_INVALID")
            if connection.execute("PRAGMA foreign_key_check;").fetchone() is not None:
                return RestoreResultV1(1, backup_ref, "REJECTED", "BACKUP_INVALID")
        finally:
            connection.close()
        _atomic_write(
            marker,
            json.dumps(
                {
                    "operation_ref": operation_ref,
                    "backup_ref": backup_ref,
                    "status": "ACCEPTED",
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        self._create_backup_record(f"pre-restore:{operation_ref}")
        temp_path = self._database_path.with_name(f".{self._database_path.name}.restore.tmp")
        shutil.copy2(backup_path, temp_path)
        with temp_path.open("rb+") as stream:
            os.fsync(stream.fileno())
        os.replace(temp_path, self._database_path)
        _atomic_write(
            marker,
            json.dumps(
                {
                    "operation_ref": operation_ref,
                    "backup_ref": backup_ref,
                    "status": "COMPLETED",
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        return RestoreResultV1(1, backup_ref, "RESTORED", None)

    def reconcile_restore(
        self, backup_ref: str, operation_ref: str
    ) -> OperationalReconcileResultV1:
        if not backup_ref.strip() or not operation_ref.strip():
            raise ValueError("backup_ref and operation_ref are required")
        marker = self._restore_marker(operation_ref)
        if marker.is_file():
            try:
                payload = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return OperationalReconcileResultV1("UNCERTAIN", None, None)
            if payload.get("backup_ref") != backup_ref:
                return OperationalReconcileResultV1("UNCERTAIN", None, None)
            if payload.get("status") == "COMPLETED":
                return OperationalReconcileResultV1(
                    "COMPLETED", backup_ref, {"backup_ref": backup_ref, "status": "RESTORED"}
                )
            manifest_path = self._backups_dir / f"{backup_ref}.manifest.json"
            if not manifest_path.is_file() or not self._database_path.is_file():
                return OperationalReconcileResultV1("SAFE_TO_RETRY", None, None)
            try:
                manifest = _manifest_from_path(manifest_path)
                if _sha256_file(self._database_path) == manifest.backup_sha256:
                    return OperationalReconcileResultV1(
                        "COMPLETED",
                        backup_ref,
                        {"backup_ref": backup_ref, "status": "RESTORED"},
                    )
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                return OperationalReconcileResultV1("UNCERTAIN", None, None)
        return OperationalReconcileResultV1("SAFE_TO_RETRY", None, None)

    def _restore_marker(self, operation_ref: str) -> Path:
        operation_hash = hashlib.sha256(operation_ref.encode("utf-8")).hexdigest()[:32]
        return self._backups_dir / f"restore-{operation_hash}.completed.json"


def _manifest_from_path(path: Path) -> BackupManifestRecord:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return BackupManifestRecord(
        backup_id=str(payload["backup_id"]),
        created_at_ms=int(payload["created_at_ms"]),
        release_version=str(payload["release_version"]),
        database_schema_version=str(payload["database_schema_version"]),
        domain_contract_version=str(payload["domain_contract_version"]),
        source_db_identity=str(payload["source_db_identity"]),
        backup_sha256=str(payload["backup_sha256"]),
        backup_size_bytes=int(payload["backup_size_bytes"]),
        quick_check_result=str(payload["quick_check_result"]),
        foreign_key_check_result=str(payload["foreign_key_check_result"]),
    )


def _metadata(record: BackupManifestRecord) -> BackupMetadataV1:
    return BackupMetadataV1(
        schema_version=1,
        backup_ref=record.backup_id,
        created_at_ms=record.created_at_ms,
        size_bytes=record.backup_size_bytes,
        manifest_hash=hashlib.sha256(
            json.dumps(asdict(record), sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _pragma_single_value(connection: sqlite3.Connection, statement: str) -> str:
    row = connection.execute(statement).fetchone()
    if row is None:
        raise ValueError(f"pragma returned no result: {statement}")
    return str(row[0])


def _atomic_write(path: Path, data: bytes) -> None:
    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp_path, path)
