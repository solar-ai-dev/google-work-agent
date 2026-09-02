"""Backup manifest and creation-result boundary contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BackupManifestRecord:
    backup_id: str
    created_at_ms: int
    release_version: str
    database_schema_version: str
    domain_contract_version: str
    source_db_identity: str
    backup_sha256: str
    backup_size_bytes: int
    quick_check_result: str
    foreign_key_check_result: str


@dataclass(frozen=True, slots=True)
class BackupCreateResult:
    backup: BackupManifestRecord
    database_path: Path
    manifest_path: Path
