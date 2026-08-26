"""SQLite online backup and restore validation helpers."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.ports import (
    BackupCreateResult,
    BackupManifestRecord,
    ClockPort,
    MaintenanceGate,
    RestorePlan,
)


class BackupIdGenerator(Protocol):
    def next_id(self) -> str: ...


class BackupService:
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
        id_generator: BackupIdGenerator,
    ) -> None:
        self._database_path = database_path
        self._backups_dir = backups_dir
        self._clock = clock
        self._maintenance_gate = maintenance_gate
        self._release_version = release_version
        self._domain_contract_version = domain_contract_version
        self._schema_version = schema_version
        self._id_generator = id_generator

    def create_backup(self) -> BackupCreateResult:
        window = self._maintenance_gate.snapshot()
        if window.has_active_write or window.migration_running or window.restore_running:
            raise ValueError("maintenance window does not allow backup")
        self._backups_dir.mkdir(parents=True, exist_ok=True)
        backup_id = self._id_generator.next_id()
        backup_path = self._backups_dir / f"{backup_id}.sqlite3"
        manifest_path = self._backups_dir / f"{backup_id}.manifest.json"
        source = connect_sqlite(self._database_path)
        try:
            destination = sqlite3.connect(str(backup_path))
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
        sha256 = _sha256_file(backup_path)
        record = BackupManifestRecord(
            backup_id=backup_id,
            created_at_ms=self._clock.now_ms(),
            release_version=self._release_version,
            database_schema_version=self._schema_version,
            domain_contract_version=self._domain_contract_version,
            source_db_identity=_sha256_file(self._database_path),
            backup_sha256=sha256,
            backup_size_bytes=backup_path.stat().st_size,
            quick_check_result=quick_check_result,
            foreign_key_check_result=foreign_key_result,
        )
        manifest_path.write_text(
            json.dumps(asdict(record), ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        self._apply_retention(now_ms=record.created_at_ms)
        return BackupCreateResult(
            backup=record,
            database_path=backup_path,
            manifest_path=manifest_path,
        )

    def list_backups(self) -> tuple[BackupManifestRecord, ...]:
        if not self._backups_dir.exists():
            return ()
        manifests = []
        for path in sorted(self._backups_dir.glob("*.manifest.json")):
            manifests.append(_manifest_from_path(path))
        manifests.sort(key=lambda item: item.created_at_ms, reverse=True)
        return tuple(manifests)

    def _apply_retention(self, *, now_ms: int) -> None:
        manifests = list(self.list_backups())
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


class RestorePlanner:
    def __init__(
        self,
        *,
        database_path: Path,
        backups_dir: Path,
        supported_schema_version: str,
        create_pre_restore_backup: Callable[[], object],
    ) -> None:
        self._database_path = database_path
        self._backups_dir = backups_dir
        self._supported_schema_version = supported_schema_version
        self._create_pre_restore_backup = create_pre_restore_backup

    def create_plan(self, backup_id: str) -> RestorePlan:
        manifest_path = self._backups_dir / f"{backup_id}.manifest.json"
        backup_path = self._backups_dir / f"{backup_id}.sqlite3"
        if not manifest_path.exists() or not backup_path.exists():
            raise ValueError("backup candidate not found")
        manifest = _manifest_from_path(manifest_path)
        if _sha256_file(backup_path) != manifest.backup_sha256:
            raise ValueError("backup hash mismatch")
        connection = sqlite3.connect(str(backup_path))
        try:
            if _pragma_single_value(connection, "PRAGMA quick_check;") != "ok":
                raise ValueError("backup quick_check failed")
            if connection.execute("PRAGMA foreign_key_check;").fetchone() is not None:
                raise ValueError("backup foreign_key_check failed")
        finally:
            connection.close()
        downgrade_blocked = int(manifest.database_schema_version) > int(
            self._supported_schema_version
        )
        self._create_pre_restore_backup()
        return RestorePlan(
            backup=manifest,
            backup_path=backup_path,
            current_db_backup_required=True,
            downgrade_blocked=downgrade_blocked,
        )


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


# BackupService retains the existing SQLite backup/retention semantics.
FilesystemBackupAdapter = BackupService
